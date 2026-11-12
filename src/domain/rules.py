import hashlib
from typing import Any, Dict
from core.config import get_config
from core.time_utils import now_ist_str


def generate_alert_id(rule_id: str, campaign_id: str) -> str:
    """Generate a stable, deterministic 5-character alert identifier."""
    raw = f"{rule_id}:{campaign_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    numeric = int(digest[:8], 16)
    return f"A{numeric % 9000 + 1000}"


def get_rule_queries(project_id: str = None) -> Dict[str, str]:
    """Return SQL queries for deterministic alert rules R1, R2, and R3."""
    config = get_config()
    project = project_id or config.gcp.project_id
    gold_dataset = config.gcp.gold_dataset
    silver_dataset = config.gcp.silver_dataset

    return {
        # R1: Low Redemption Rate (< 5% of targeted customer audience)
        "R1": f"""
            WITH campaign_fact AS (
                SELECT
                    campaign_id,
                    merchant_id,
                    ROUND(
                        SAFE_DIVIDE(
                            redeeming_customer_count,
                            NULLIF(targeted_customer_count, 0)
                        ) * 100,
                        2
                    ) AS redemption_rate
                FROM `{project}.{gold_dataset}.gold_campaign_results`
                WHERE targeted_customer_count > 0
            )
            SELECT
                campaign_id,
                merchant_id,
                'R1' AS rule_id,
                'redemption_rate' AS metric_name,
                redemption_rate AS metric_value,
                5.00 AS threshold,
                'OPEN' AS status
            FROM campaign_fact
            WHERE redemption_rate < 5.00
            ORDER BY campaign_id
        """,

        # R2: Sudden Drop in Redemption Rate Between Comparable Periods
        "R2": f"""
            WITH campaign_txns AS (
                SELECT
                    c.campaign_id,
                    c.merchant_id,
                    c.start_date,
                    c.end_date,
                    DATE_DIFF(c.end_date, c.start_date, DAY) / 2 AS mid_point_days,
                    DATE_ADD(c.start_date, INTERVAL CAST(FLOOR(DATE_DIFF(c.end_date, c.start_date, DAY) / 2) AS INT64) DAY) AS mid_date,
                    r.customer_id,
                    r.awarded_at
                FROM `{project}.{silver_dataset}.campaigns` c
                JOIN `{project}.{silver_dataset}.offer_redemptions` r
                    ON r.campaign_id = c.campaign_id
                WHERE UPPER(r.status) = 'AWARDED'
                  AND c.status = 'ACTIVE'
            ),
            sends AS (
                SELECT
                    campaign_id,
                    COUNT(DISTINCT customer_id) AS targeted_customers
                FROM `{project}.{silver_dataset}.offer_sends`
                GROUP BY campaign_id
            ),
            period_metrics AS (
                SELECT
                    ct.campaign_id,
                    ct.merchant_id,
                    s.targeted_customers,
                    COUNT(DISTINCT CASE WHEN DATE(ct.awarded_at) <= ct.mid_date THEN ct.customer_id END) AS p1_redeemers,
                    COUNT(DISTINCT CASE WHEN DATE(ct.awarded_at) > ct.mid_date THEN ct.customer_id END) AS p2_redeemers
                FROM campaign_txns ct
                JOIN sends s ON s.campaign_id = ct.campaign_id
                GROUP BY ct.campaign_id, ct.merchant_id, s.targeted_customers
            ),
            period_rates AS (
                SELECT
                    campaign_id,
                    merchant_id,
                    ROUND(SAFE_DIVIDE(p1_redeemers, targeted_customers) * 100, 2) AS p1_rate,
                    ROUND(SAFE_DIVIDE(p2_redeemers, targeted_customers) * 100, 2) AS p2_rate
                FROM period_metrics
                WHERE targeted_customers > 0
            )
            SELECT
                campaign_id,
                merchant_id,
                'R2' AS rule_id,
                'period_redemption_drop_pct' AS metric_name,
                p2_rate AS metric_value,
                ROUND(p1_rate * 0.50, 2) AS threshold,
                'OPEN' AS status
            FROM period_rates
            WHERE p1_rate >= 10.00
              AND p2_rate <= (p1_rate * 0.50)
            ORDER BY campaign_id
        """,

        # R3: Dominance of Existing Customers in New-Customer Acquisition Campaigns (>= 75%)
        "R3": f"""
            WITH redeeming_customers AS (
                SELECT
                    c.campaign_id,
                    c.merchant_id,
                    rr.customer_id,
                    MAX(
                        CASE
                            WHEN CAST(tx.txn_ts AS DATETIME) < DATETIME(c.start_date)
                             AND tx.merchant_id = c.merchant_id
                             AND UPPER(tx.txn_status) = 'POSTED'
                            THEN 1
                            ELSE 0
                        END
                    ) AS is_existing_customer
                FROM `{project}.{silver_dataset}.offer_redemptions` rr
                INNER JOIN `{project}.{silver_dataset}.campaigns` c
                    ON c.campaign_id = rr.campaign_id
                LEFT JOIN `{project}.{silver_dataset}.transactions` tx
                    ON tx.customer_id = rr.customer_id
                   AND tx.merchant_id = c.merchant_id
                   AND UPPER(tx.txn_status) = 'POSTED'
                   AND CAST(tx.txn_ts AS DATETIME) < DATETIME(c.start_date)
                WHERE UPPER(c.objective) = 'ACQUIRE_NEW'
                  AND UPPER(rr.status) = 'AWARDED'
                GROUP BY
                    c.campaign_id,
                    c.merchant_id,
                    rr.customer_id
            ),
            campaign_fact AS (
                SELECT
                    campaign_id,
                    merchant_id,
                    COUNT(DISTINCT customer_id) AS redeeming_customers,
                    COUNT(DISTINCT CASE WHEN is_existing_customer = 1 THEN customer_id END) AS existing_customer_redeemers,
                    ROUND(
                        SAFE_DIVIDE(
                            COUNT(DISTINCT CASE WHEN is_existing_customer = 1 THEN customer_id END),
                            COUNT(DISTINCT customer_id)
                        ) * 100,
                        2
                    ) AS existing_customer_share
                FROM redeeming_customers
                GROUP BY
                    campaign_id,
                    merchant_id
            )
            SELECT
                campaign_id,
                merchant_id,
                'R3' AS rule_id,
                'existing_customer_share_pct' AS metric_name,
                existing_customer_share AS metric_value,
                75.00 AS threshold,
                'OPEN' AS status
            FROM campaign_fact
            WHERE existing_customer_share >= 75.00
            ORDER BY campaign_id
        """
    }


def parse_alert_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Construct an AlertPayload dictionary from a SQL result row."""
    rule_id = str(row["rule_id"])
    campaign_id = str(row["campaign_id"])
    return {
        "alert_id": generate_alert_id(rule_id, campaign_id),
        "campaign_id": campaign_id,
        "merchant_id": row.get("merchant_id"),
        "rule_id": rule_id,
        "metric_name": row.get("metric_name", "unknown_metric"),
        "metric_value": float(row["metric_value"]),
        "threshold_value": float(row["threshold"]),
        "status": row.get("status", "OPEN"),
        "created_at": str(row.get("created_at") or now_ist_str()),
    }
