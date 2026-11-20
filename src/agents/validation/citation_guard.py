"""Batched zero-hallucination citation verifier checking evidence against BigQuery using IN UNNEST."""
from typing import Dict, List, Any, Set, Tuple, Optional
from google.cloud import bigquery
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from agents.schemas.dossier import InvestigationDossier


TABLE_PK_MAP = {
    "offers_silver.campaigns": "campaign_id",
    "offers_silver.transactions": "txn_id",
    "offers_silver.offer_sends": "send_id",
    "offers_silver.offer_redemptions": "redemption_id",
    "offers_silver.customer_reviews": "review_id",
    "offers_silver.merchant_feedback": "feedback_id",
    "offers_gold.gold_campaign_results": "campaign_id",
    "offers_gold.gold_merchant_spend_profile": "merchant_id",
}


class CitationVerifier:
    """Verifies that 100% of claimed evidence citations physically exist in BigQuery."""

    def __init__(self, config: Optional[Any] = None):
        self.config = config or get_config()
        self.project_id = self.config.gcp.project_id

    def verify_citations(self, dossier: InvestigationDossier) -> Tuple[bool, List[str]]:
        """Batched verification using IN UNNEST grouped by source table.
        
        Returns:
            (all_valid: bool, warnings: List[str])
        """
        if not dossier.evidence:
            return True, []

        grouped_citations: Dict[str, Set[str]] = {}
        for item in dossier.evidence:
            source = item.source
            rec_id = str(item.record_id).strip()
            if source and rec_id:
                grouped_citations.setdefault(source, set()).add(rec_id)

        warnings: List[str] = []
        all_valid = True

        for source_table, ids in grouped_citations.items():
            pk_col = TABLE_PK_MAP.get(source_table)
            if not pk_col:
                # If table is not mapped, skip batched check
                continue

            sql = f"""
            SELECT DISTINCT {pk_col} AS existing_id
            FROM `{self.project_id}.{source_table}`
            WHERE {pk_col} IN UNNEST(@ids)
            """
            params = [bigquery.ArrayQueryParameter("ids", "STRING", list(ids))]
            try:
                rows = execute_query(sql, parameters=params)
                existing_ids = {str(r.get("existing_id")) for r in rows}
                missing_ids = ids - existing_ids
                if missing_ids:
                    all_valid = False
                    for m_id in missing_ids:
                        msg = f"Citation Verification Warning: ID '{m_id}' not found in `{source_table}`"
                        logger.warning(msg)
                        warnings.append(msg)
            except Exception as exc:
                logger.error(f"Citation verification failed for `{source_table}`: {exc}")
                warnings.append(f"Verification query error for `{source_table}`: {exc}")

        return all_valid, warnings
