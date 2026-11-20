from typing import Any, Dict
from google.cloud import bigquery
import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from domain.policy import PolicyValidator


class HistoricalReplaySimulator:
    """Simulates retrospective campaign modifications against historical posted transactions."""

    def __init__(self, client=None, policy_validator=None):
        self.client = client
        self.validator = policy_validator or PolicyValidator()
        self.config = get_config()

    def simulate(self, campaign_id: str, proposed_min_spend: float) -> Dict[str, Any]:
        """Replay proposed spend threshold against targeted customers' historical transactions."""
        try:
            min_spend = float(proposed_min_spend)
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": "proposed_min_spend must be a valid numeric value",
                "campaign_id": campaign_id,
                "status": "FAILED",
            }

        # Step 1: Pre-validate proposal against campaign policy allowlist
        validation = self.validator.validate_proposal(
            proposed_min_spend=min_spend,
            cashback_pct=self.config.policy.cashback_percent,
            cashback_cap=self.config.policy.cashback_cap,
        )
        if not validation["allowed"]:
            return {
                "success": False,
                "error": f"Proposal rejected by policy: {validation['reason']}",
                "campaign_id": campaign_id,
                "status": "REJECTED_BY_POLICY",
            }

        project = self.config.gcp.project_id
        silver = self.config.gcp.silver_dataset

        sql = f"""
            WITH campaign AS (
                SELECT
                    campaign_id,
                    merchant_id,
                    start_date,
                    end_date,
                    budget,
                    cashback_pct,
                    cashback_cap,
                    COALESCE(max_redemptions_per_customer, 1) AS max_red,
                    min_spend AS current_min_spend
                FROM `{project}.{silver}.campaigns`
                WHERE campaign_id = @campaign_id
            ),
            targeted AS (
                SELECT DISTINCT campaign_id, customer_id
                FROM `{project}.{silver}.offer_sends`
                WHERE campaign_id = @campaign_id
            ),
            scenarios AS (
                SELECT 'current' AS scenario, current_min_spend AS min_spend FROM campaign
                UNION ALL
                SELECT 'proposed' AS scenario, @proposed_min_spend AS min_spend FROM campaign
            ),
            ranked_txns AS (
                SELECT
                    s.scenario,
                    t.customer_id,
                    t.amount,
                    c.cashback_pct,
                    c.cashback_cap,
                    c.max_red,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.scenario, t.customer_id
                        ORDER BY t.txn_ts ASC
                    ) AS rn
                FROM campaign c
                CROSS JOIN scenarios s
                JOIN targeted tgt ON tgt.campaign_id = c.campaign_id
                JOIN `{project}.{silver}.transactions` t
                    ON t.merchant_id = c.merchant_id
                   AND t.customer_id = tgt.customer_id
                WHERE UPPER(t.txn_status) = 'POSTED'
                  AND DATE(t.txn_ts) BETWEEN c.start_date AND c.end_date
                  AND t.amount >= s.min_spend
            )
            SELECT
                s.scenario,
                s.min_spend,
                c.budget,
                COUNT(1) AS total_qualifying_txns,
                COUNTIF(r.rn <= r.max_red) AS eligible_txns,
                COUNT(DISTINCT IF(r.rn <= r.max_red, r.customer_id, NULL)) AS unique_customers,
                ROUND(
                    SUM(
                        IF(
                            r.rn <= r.max_red,
                            LEAST(r.amount * r.cashback_pct / 100, r.cashback_cap),
                            0
                        )
                    ),
                    2
                ) AS simulated_cashback
            FROM campaign c
            CROSS JOIN scenarios s
            LEFT JOIN ranked_txns r ON r.scenario = s.scenario
            GROUP BY s.scenario, s.min_spend, c.budget
        """

        parameters = [
            bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id),
            bigquery.ScalarQueryParameter("proposed_min_spend", "NUMERIC", min_spend),
        ]

        try:
            rows = bq_client.execute_query(sql, parameters=parameters, client=self.client)
            results_by_scenario = {r["scenario"]: r for r in rows}

            if "current" not in results_by_scenario or "proposed" not in results_by_scenario:
                return {
                    "success": False,
                    "error": f"Campaign '{campaign_id}' not found or transaction data missing",
                    "campaign_id": campaign_id,
                    "status": "FAILED",
                }

            curr = results_by_scenario["current"]
            prop = results_by_scenario["proposed"]

            curr_cashback = float(curr.get("simulated_cashback") or 0.0)
            prop_cashback = float(prop.get("simulated_cashback") or 0.0)
            curr_cust = int(curr.get("unique_customers") or 0)
            prop_cust = int(prop.get("unique_customers") or 0)
            curr_txns = int(curr.get("eligible_txns") or 0)
            prop_txns = int(prop.get("eligible_txns") or 0)
            budget = float(prop.get("budget") or 0.0)

            budget_safe = prop_cashback <= budget if budget > 0 else True

            return {
                "success": True,
                "campaign_id": campaign_id,
                "simulation_type": "HISTORICAL_REPLAY",
                "current_scenario": curr,
                "proposed_scenario": prop,
                "delta": {
                    "additional_customers": prop_cust - curr_cust,
                    "additional_txns": prop_txns - curr_txns,
                    "additional_cashback": round(prop_cashback - curr_cashback, 2),
                },
                "budget": budget,
                "budget_safe": budget_safe,
                "status": "APPROVED_REPLAY",
                "disclaimer": (
                    "Historical replay measures retrospective eligibility on observed transactions. "
                    "It does NOT forecast future customer visits, behavioral elasticity, or incremental revenue."
                ),
            }
        except Exception as exc:
            logger.error(f"Error during historical replay for campaign '{campaign_id}': {exc}")
            return {
                "success": False,
                "error": f"Failed simulating campaign change: {str(exc)}",
                "campaign_id": campaign_id,
                "status": "FAILED",
            }
