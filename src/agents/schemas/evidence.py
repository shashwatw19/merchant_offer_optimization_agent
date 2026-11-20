from typing import Any, Dict
from pydantic import BaseModel, Field, model_validator


VALID_SOURCES = {
    "offers_silver.campaigns",
    "offers_silver.transactions",
    "offers_silver.offer_sends",
    "offers_silver.offer_redemptions",
    "offers_silver.customer_reviews",
    "offers_silver.merchant_feedback",
    "offers_gold.gold_campaign_results",
    "offers_gold.gold_merchant_spend_profile",
}


def normalize_source_and_id(raw_ref: str) -> tuple[str, str]:
    """Extracts a recognized BigQuery source table and record ID from any evidence ref."""
    clean = raw_ref.replace("bq:", "").strip()
    parts = clean.split(":")
    table_part = parts[0].strip()
    record_id = parts[1].strip() if len(parts) > 1 else ""

    # Match known silver/gold tables inside full qualified references
    for valid in VALID_SOURCES:
        if valid in table_part:
            return valid, record_id or table_part.split(".")[-1]

    # Handle dataset.table format
    tokens = table_part.split(".")
    if len(tokens) >= 2:
        short = f"{tokens[-2]}.{tokens[-1]}"
        if short in VALID_SOURCES:
            return short, record_id

    return table_part, record_id


class EvidenceItem(BaseModel):
    """Structured citation item pointing to an audit-verifiable BigQuery record."""
    source: str = Field(
        default="offers_silver.campaigns",
        description="The source table where this record resides"
    )
    record_id: str = Field(
        default="",
        description="The primary key of the cited record (e.g. 'CMP131', 'TXN_4509', 'REV_108')"
    )
    fact: str = Field(
        default="",
        description="The factual observation directly derived from this record"
    )

    @model_validator(mode="before")
    @classmethod
    def parse_flexible_evidence(cls, data: Any) -> Dict[str, Any]:
        if isinstance(data, str):
            source, rec_id = normalize_source_and_id(data)
            return {
                "source": source,
                "record_id": rec_id or data,
                "fact": f"Evidence derived from {data}",
            }
        if isinstance(data, dict):
            src = str(data.get("source", "")).strip()
            rec = str(data.get("record_id", "")).strip()
            fact = str(data.get("fact", "")).strip()
            
            # If source looks like a composite ref (e.g. bq:project.dataset.table:id)
            if ":" in src or "bq:" in src or "." in src:
                norm_src, norm_rec = normalize_source_and_id(src)
                src = norm_src
                if not rec:
                    rec = norm_rec

            return {
                "source": src or "offers_silver.campaigns",
                "record_id": rec or "RECORD",
                "fact": fact or f"Observed from {src}",
            }
        return {"source": "offers_silver.campaigns", "record_id": str(data), "fact": str(data)}
