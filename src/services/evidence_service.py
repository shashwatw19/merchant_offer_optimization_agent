"""Evidence Verification Service.

Resolves evidence citations from agent investigation reports (e.g.
'bq:offers_silver.campaigns:CMP131', 'review_id: REV_108', 'bq:gold_results')
to the underlying Bronze raw tables in BigQuery, retrieves the exact source
records, and returns structured provenance data for verification.
"""

import re
from typing import Any, Dict, List, Optional
from google.cloud import bigquery

import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger


class EvidenceResolver:
    """Resolves report evidence references to Bronze-layer BigQuery records."""

    def __init__(self, config: Optional[Any] = None):
        self.config = config or get_config()
        self.project_id = self.config.gcp.project_id
        self.bronze_dataset = self.config.gcp.bronze_dataset
        self.silver_dataset = self.config.gcp.silver_dataset
        self.gold_dataset = self.config.gcp.gold_dataset

    def _mask_sensitive_data(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Mask sensitive PII fields in raw data records before returning to the UI."""
        masked_records = []
        sensitive_keys = {"card_number", "pan", "account_number", "ssn", "password", "token"}
        
        for record in records:
            cleaned = {}
            for k, v in record.items():
                if any(sk in k.lower() for sk in sensitive_keys):
                    val_str = str(v)
                    cleaned[k] = f"****-****-****-{val_str[-4:]}" if len(val_str) >= 4 else "********"
                else:
                    cleaned[k] = v
            masked_records.append(cleaned)
        return masked_records

    def resolve_evidence(
        self,
        evidence_ref: str,
        campaign_id: Optional[str] = None,
        merchant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resolve an evidence citation to its underlying Bronze table and records."""
        ref = (evidence_ref or "").strip()
        ref_lower = ref.lower()

        logger.info(f"Resolving evidence reference: '{ref}' (Campaign: {campaign_id}, Merchant: {merchant_id})")

        # 1. Detect Customer Review Reference
        if "customer_review" in ref_lower or "review" in ref_lower:
            return self._resolve_review(ref, merchant_id)

        # 2. Detect Merchant Feedback Reference
        if "merchant_feedback" in ref_lower or "feedback" in ref_lower:
            return self._resolve_feedback(ref, merchant_id)

        # 3. Detect Delivery / Offer Send Reference
        if "offer_send" in ref_lower or "delivery" in ref_lower:
            return self._resolve_delivery(ref, campaign_id)

        # 4. Detect Gold Aggregate Results Reference (before generic campaign check)
        if "gold_campaign_results" in ref_lower or "gold_results" in ref_lower or (
            "gold" in ref_lower and "results" in ref_lower
        ):
            return self._resolve_gold_results(ref, campaign_id)

        # 5. Detect Spend Profile / Transaction Reference
        if "spend_profile" in ref_lower or "transaction" in ref_lower or "spend" in ref_lower:
            return self._resolve_spend(ref, merchant_id)

        # 6. Detect Campaign Terms Reference
        if "campaign" in ref_lower or ref.startswith("CMP"):
            return self._resolve_campaign(ref, campaign_id)

        # 7. Detect Rule Reference (e.g. rule:R1, R1)
        if "rule:" in ref_lower or ref_lower in ("r1", "r2", "r3"):
            return self._resolve_rule(ref, campaign_id)

        # Default fallback: Try campaign or merchant resolution
        if campaign_id:
            return self._resolve_campaign(ref, campaign_id)

        return {
            "success": False,
            "evidence_ref": ref,
            "source_layer": "UNKNOWN",
            "source_table": "None",
            "record_count": 0,
            "records": [],
            "verification_verdict": "UNRECOGNIZED_CITATION_FORMAT",
            "explanation": f"Could not determine the target Bronze table for reference '{ref}'.",
        }

    def _resolve_campaign(self, ref: str, fallback_campaign_id: Optional[str]) -> Dict[str, Any]:
        cid_match = re.search(r"CMP\d+", ref, re.IGNORECASE)
        cid = cid_match.group(0).upper() if cid_match else (fallback_campaign_id or "CMP131")

        bronze_table = f"{self.project_id}.{self.bronze_dataset}.campaigns_raw"
        silver_table = f"{self.project_id}.{self.silver_dataset}.campaigns"

        sql = f"""
            SELECT
                campaign_id,
                merchant_id,
                objective,
                start_date,
                end_date,
                min_spend,
                cashback_pct,
                cashback_cap,
                budget,
                funding_type,
                max_redemptions_per_customer,
                status,
                batch_id,
                ingestion_ts
            FROM `{bronze_table}`
            WHERE campaign_id = @campaign_id
            LIMIT 5
        """
        params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", cid)]
        try:
            rows = bq_client.execute_query(sql, parameters=params)
            masked = self._mask_sensitive_data(rows)
            batch_id = rows[0].get("batch_id") if rows else "N/A"
            ingestion_ts = rows[0].get("ingestion_ts") if rows else "N/A"

            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "CAMPAIGN_TERMS",
                "source_layer": "BRONZE (Raw Ingestion Layer)",
                "source_table": bronze_table,
                "silver_table": silver_table,
                "resolved_id": cid,
                "batch_id": batch_id,
                "ingestion_ts": ingestion_ts,
                "record_count": len(rows),
                "records": masked,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_table, "role": "Raw immutable ingestion from campaigns.csv"},
                    {"layer": "Silver", "table": silver_table, "role": "Cleaned, typed, active campaign terms"},
                ],
                "verification_verdict": "VERIFIED_SOURCE_RECORD" if rows else "RECORD_NOT_FOUND",
                "explanation": f"Retrieved source campaign parameters from Bronze raw ingestion table for campaign {cid}.",
            }
        except Exception as exc:
            logger.warning(f"Bronze query for campaign {cid} failed: {exc}")
            return self._build_query_error_response(ref, bronze_table, silver_table, cid, exc)

    def _resolve_review(self, ref: str, fallback_merchant_id: Optional[str]) -> Dict[str, Any]:
        rid_match = re.search(r"REV_?\d+", ref, re.IGNORECASE)
        mid_match = re.search(r"M\d+", ref, re.IGNORECASE)

        review_id = rid_match.group(0).upper().replace("_", "") if rid_match else None
        merchant_id = mid_match.group(0).upper() if mid_match else (fallback_merchant_id or "M001")

        bronze_table = f"{self.project_id}.{self.bronze_dataset}.customer_reviews_raw"
        silver_table = f"{self.project_id}.{self.silver_dataset}.customer_reviews"

        if review_id:
            sql = f"""
                SELECT
                    review_id,
                    merchant_id,
                    review_date,
                    collected_at,
                    rating,
                    review_text,
                    source_ref,
                    batch_id,
                    ingestion_ts
                FROM `{bronze_table}`
                WHERE UPPER(REPLACE(review_id, '_', '')) = @review_id
                LIMIT 5
            """
            params = [bigquery.ScalarQueryParameter("review_id", "STRING", review_id)]
            resolved_id = review_id
        else:
            sql = f"""
                SELECT
                    review_id,
                    merchant_id,
                    review_date,
                    collected_at,
                    rating,
                    review_text,
                    source_ref,
                    batch_id,
                    ingestion_ts
                FROM `{bronze_table}`
                WHERE merchant_id = @merchant_id
                ORDER BY review_date DESC
                LIMIT 5
            """
            params = [bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id)]
            resolved_id = merchant_id

        try:
            rows = bq_client.execute_query(sql, parameters=params)
            masked = self._mask_sensitive_data(rows)
            batch_id = rows[0].get("batch_id") if rows else "N/A"
            ingestion_ts = rows[0].get("ingestion_ts") if rows else "N/A"

            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "CUSTOMER_REVIEWS",
                "source_layer": "BRONZE (Raw Ingestion Layer)",
                "source_table": bronze_table,
                "silver_table": silver_table,
                "resolved_id": resolved_id,
                "batch_id": batch_id,
                "ingestion_ts": ingestion_ts,
                "record_count": len(rows),
                "records": masked,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_table, "role": "Raw immutable ingestion from customer_reviews.csv"},
                    {"layer": "Silver", "table": silver_table, "role": "Standardized ratings and timestamps"},
                ],
                "verification_verdict": "VERIFIED_SOURCE_RECORD" if rows else "RECORD_NOT_FOUND",
                "explanation": f"Retrieved raw dated customer reviews and ratings from Bronze table for {resolved_id}.",
            }
        except Exception as exc:
            logger.warning(f"Bronze query for reviews failed: {exc}")
            return self._build_query_error_response(ref, bronze_table, silver_table, resolved_id, exc)

    def _resolve_feedback(self, ref: str, fallback_merchant_id: Optional[str]) -> Dict[str, Any]:
        fbid_match = re.search(r"FB_?\d+", ref, re.IGNORECASE)
        mid_match = re.search(r"M\d+", ref, re.IGNORECASE)

        feedback_id = fbid_match.group(0).upper().replace("_", "") if fbid_match else None
        merchant_id = mid_match.group(0).upper() if mid_match else (fallback_merchant_id or "M001")

        bronze_table = f"{self.project_id}.{self.bronze_dataset}.merchant_feedback_raw"
        silver_table = f"{self.project_id}.{self.silver_dataset}.merchant_feedback"

        if feedback_id:
            sql = f"""
                SELECT
                    feedback_id,
                    merchant_id,
                    event_date,
                    recorded_at,
                    feedback_text,
                    source_ref,
                    verification_status,
                    batch_id,
                    ingestion_ts
                FROM `{bronze_table}`
                WHERE UPPER(REPLACE(feedback_id, '_', '')) = @feedback_id
                LIMIT 5
            """
            params = [bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id)]
            resolved_id = feedback_id
        else:
            sql = f"""
                SELECT
                    feedback_id,
                    merchant_id,
                    event_date,
                    recorded_at,
                    feedback_text,
                    source_ref,
                    verification_status,
                    batch_id,
                    ingestion_ts
                FROM `{bronze_table}`
                WHERE merchant_id = @merchant_id
                ORDER BY event_date DESC
                LIMIT 5
            """
            params = [bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id)]
            resolved_id = merchant_id

        try:
            rows = bq_client.execute_query(sql, parameters=params)
            masked = self._mask_sensitive_data(rows)
            batch_id = rows[0].get("batch_id") if rows else "N/A"
            ingestion_ts = rows[0].get("ingestion_ts") if rows else "N/A"

            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "MERCHANT_FEEDBACK",
                "source_layer": "BRONZE (Raw Ingestion Layer)",
                "source_table": bronze_table,
                "silver_table": silver_table,
                "resolved_id": resolved_id,
                "batch_id": batch_id,
                "ingestion_ts": ingestion_ts,
                "record_count": len(rows),
                "records": masked,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_table, "role": "Raw immutable ingestion from merchant_feedback.csv"},
                    {"layer": "Silver", "table": silver_table, "role": "Operational incident log with verification tags"},
                ],
                "verification_verdict": "VERIFIED_SOURCE_RECORD" if rows else "RECORD_NOT_FOUND",
                "explanation": f"Retrieved merchant operational incident notes from Bronze table for {resolved_id}.",
            }
        except Exception as exc:
            logger.warning(f"Bronze query for feedback failed: {exc}")
            return self._build_query_error_response(ref, bronze_table, silver_table, resolved_id, exc)

    def _resolve_delivery(self, ref: str, fallback_campaign_id: Optional[str]) -> Dict[str, Any]:
        cid_match = re.search(r"CMP\d+", ref, re.IGNORECASE)
        cid = cid_match.group(0).upper() if cid_match else (fallback_campaign_id or "CMP131")

        bronze_table = f"{self.project_id}.{self.bronze_dataset}.offer_sends_raw"
        silver_table = f"{self.project_id}.{self.silver_dataset}.offer_sends"

        sql = f"""
            SELECT
                send_id,
                campaign_id,
                customer_id,
                channel,
                send_date,
                delivery_status,
                batch_id,
                ingestion_ts
            FROM `{bronze_table}`
            WHERE campaign_id = @campaign_id
            LIMIT 10
        """
        params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", cid)]
        try:
            rows = bq_client.execute_query(sql, parameters=params)
            masked = self._mask_sensitive_data(rows)
            batch_id = rows[0].get("batch_id") if rows else "N/A"
            ingestion_ts = rows[0].get("ingestion_ts") if rows else "N/A"

            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "OFFER_SENDS",
                "source_layer": "BRONZE (Raw Ingestion Layer)",
                "source_table": bronze_table,
                "silver_table": silver_table,
                "resolved_id": cid,
                "batch_id": batch_id,
                "ingestion_ts": ingestion_ts,
                "record_count": len(rows),
                "records": masked,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_table, "role": "Raw immutable ingestion from offer_sends.csv"},
                    {"layer": "Silver", "table": silver_table, "role": "Delivery metrics and geographical targeting alignment"},
                ],
                "verification_verdict": "VERIFIED_SOURCE_RECORD" if rows else "RECORD_NOT_FOUND",
                "explanation": f"Retrieved raw communication delivery records from Bronze table for campaign {cid}.",
            }
        except Exception as exc:
            logger.warning(f"Bronze query for offer sends failed: {exc}")
            return self._build_query_error_response(ref, bronze_table, silver_table, cid, exc)

    def _resolve_spend(self, ref: str, fallback_merchant_id: Optional[str]) -> Dict[str, Any]:
        mid_match = re.search(r"M\d+", ref, re.IGNORECASE)
        mid = mid_match.group(0).upper() if mid_match else (fallback_merchant_id or "M001")

        bronze_table = f"{self.project_id}.{self.bronze_dataset}.transactions_raw"
        gold_table = f"{self.project_id}.{self.gold_dataset}.gold_merchant_spend_profile"

        sql = f"""
            SELECT
                txn_id,
                merchant_id,
                customer_id,
                txn_timestamp,
                amount,
                txn_status,
                batch_id,
                ingestion_ts
            FROM `{bronze_table}`
            WHERE merchant_id = @merchant_id
            LIMIT 10
        """
        params = [bigquery.ScalarQueryParameter("merchant_id", "STRING", mid)]
        try:
            rows = bq_client.execute_query(sql, parameters=params)
            masked = self._mask_sensitive_data(rows)
            batch_id = rows[0].get("batch_id") if rows else "N/A"
            ingestion_ts = rows[0].get("ingestion_ts") if rows else "N/A"

            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "SPEND_TRANSACTIONS",
                "source_layer": "BRONZE (Raw Ingestion Layer)",
                "source_table": bronze_table,
                "gold_table": gold_table,
                "resolved_id": mid,
                "batch_id": batch_id,
                "ingestion_ts": ingestion_ts,
                "record_count": len(rows),
                "records": masked,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_table, "role": "Raw immutable bank-card transactions from transactions.csv"},
                    {"layer": "Gold", "table": gold_table, "role": "Aggregated spend distribution and median ticket size"},
                ],
                "verification_verdict": "VERIFIED_SOURCE_RECORD" if rows else "RECORD_NOT_FOUND",
                "explanation": f"Retrieved raw bank transaction sample from Bronze table supporting spend distribution for merchant {mid}.",
            }
        except Exception as exc:
            logger.warning(f"Bronze query for transactions failed: {exc}")
            return self._build_query_error_response(ref, bronze_table, gold_table, mid, exc)

    def _resolve_gold_results(self, ref: str, fallback_campaign_id: Optional[str]) -> Dict[str, Any]:
        cid_match = re.search(r"CMP\d+", ref, re.IGNORECASE)
        cid = cid_match.group(0).upper() if cid_match else (fallback_campaign_id or "CMP131")

        gold_table = f"{self.project_id}.{self.gold_dataset}.gold_campaign_results"
        bronze_campaigns = f"{self.project_id}.{self.bronze_dataset}.campaigns_raw"
        bronze_sends = f"{self.project_id}.{self.bronze_dataset}.offer_sends_raw"
        bronze_redemptions = f"{self.project_id}.{self.bronze_dataset}.offer_redemptions_raw"

        sql = f"""
            SELECT
                campaign_id,
                merchant_id,
                targeted_customer_count,
                delivered_customer_count,
                redeeming_customer_count,
                redemption_rate_pct,
                cashback_amt_awarded,
                posted_txn_count,
                posted_txn_amount
            FROM `{gold_table}`
            WHERE campaign_id = @campaign_id
            LIMIT 1
        """
        params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", cid)]
        try:
            rows = bq_client.execute_query(sql, parameters=params)
            return {
                "success": True,
                "evidence_ref": ref,
                "target_type": "GOLD_AGGREGATE",
                "source_layer": "GOLD (Derived Business Aggregate)",
                "source_table": gold_table,
                "resolved_id": cid,
                "record_count": len(rows),
                "records": rows,
                "lineage": [
                    {"layer": "Bronze", "table": bronze_campaigns, "role": "Campaign configuration"},
                    {"layer": "Bronze", "table": bronze_sends, "role": "Targeted audience and delivered counts"},
                    {"layer": "Bronze", "table": bronze_redemptions, "role": "Redemptions and cashback awarded"},
                    {"layer": "Gold", "table": gold_table, "role": "Aggregated redemption rate and financial impact"},
                ],
                "verification_verdict": "DERIVED_AGGREGATE_METRIC",
                "explanation": (
                    f"Campaign aggregate results from Gold layer for {cid}. "
                    f"Derived deterministically from underlying Bronze tables: campaigns_raw, offer_sends_raw, and offer_redemptions_raw."
                ),
            }
        except Exception as exc:
            logger.warning(f"Gold results query failed: {exc}")
            return self._build_query_error_response(ref, gold_table, "None", cid, exc)

    def _resolve_rule(self, ref: str, fallback_campaign_id: Optional[str]) -> Dict[str, Any]:
        rule_id = "R1"
        if "r2" in ref.lower():
            rule_id = "R2"
        elif "r3" in ref.lower():
            rule_id = "R3"

        rule_descriptions = {
            "R1": "Low Redemption Rate (< 5% of targeted customer audience). Derived from gold_campaign_results.",
            "R2": "Sudden Drop in Redemption Rate (Period 2 rate <= 50% of Period 1). Derived from offer_redemptions_raw and offer_sends_raw.",
            "R3": "Dominance of Existing Customers (>= 75% in new customer campaign). Derived from transactions_raw, offer_redemptions_raw.",
        }

        return {
            "success": True,
            "evidence_ref": ref,
            "target_type": "RULE_DEFINITION",
            "source_layer": "BUSINESS_RULE_ENGINE",
            "source_table": f"{self.project_id}.{self.gold_dataset}.alerts",
            "resolved_id": rule_id,
            "record_count": 1,
            "records": [{"rule_id": rule_id, "definition": rule_descriptions.get(rule_id)}],
            "lineage": [
                {"layer": "Rules Engine", "table": "src/domain/rules.py", "role": f"Deterministic SQL rule query for {rule_id}"},
                {"layer": "Alerts Table", "table": f"{self.project_id}.{self.gold_dataset}.alerts", "role": "Alert storage"}
            ],
            "verification_verdict": "RULE_POLICY_EVALUATION",
            "explanation": rule_descriptions.get(rule_id, "System alert evaluation rule."),
        }

    def _build_query_error_response(
        self,
        ref: str,
        source_table: str,
        silver_table: str,
        resolved_id: str,
        exc: Exception,
    ) -> Dict[str, Any]:
        return {
            "success": False,
            "evidence_ref": ref,
            "target_type": "QUERY_ERROR",
            "source_layer": "BRONZE",
            "source_table": source_table,
            "silver_table": silver_table,
            "resolved_id": resolved_id,
            "record_count": 0,
            "records": [],
            "verification_verdict": "DATA_UNAVAILABLE",
            "error": str(exc),
            "explanation": f"Failed to retrieve source records from `{source_table}` for '{resolved_id}': {exc}",
        }


_EVIDENCE_RESOLVER: Optional[EvidenceResolver] = None


def get_evidence_resolver() -> EvidenceResolver:
    """Return singleton instance of EvidenceResolver."""
    global _EVIDENCE_RESOLVER
    if _EVIDENCE_RESOLVER is None:
        _EVIDENCE_RESOLVER = EvidenceResolver()
    return _EVIDENCE_RESOLVER
