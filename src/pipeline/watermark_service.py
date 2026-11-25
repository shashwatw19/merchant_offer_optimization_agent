"""High-watermark state tracking, GCS ingestion ledger, and monotonic batch generation."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import bigquery

from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from services.gcs_storage import get_storage_client

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class EntitySpec:
    """Pipeline metadata for a single medallion entity."""

    name: str
    bronze_table: str
    silver_table: str
    ext_table: str
    pk_column: str
    silver_sql: str
    columns: Tuple[str, ...]
    ts_column: Optional[str] = None
    fallback_ts_column: Optional[str] = None
    aliases: Tuple[str, ...] = ()


ENTITY_SPECS: Tuple[EntitySpec, ...] = (
    EntitySpec(
        name="merchants",
        bronze_table="merchants_raw",
        silver_table="merchants",
        ext_table="ext_merchants",
        pk_column="merchant_id",
        silver_sql="sql/silver/merchants.sql",
        columns=("merchant_id", "name", "category", "city", "status"),
        aliases=("merchants", "merchant"),
    ),
    EntitySpec(
        name="customers",
        bronze_table="customers_raw",
        silver_table="customers",
        ext_table="ext_customers",
        pk_column="customer_id",
        silver_sql="sql/silver/customers.sql",
        columns=("customer_id", "city", "segment", "marketing_eligible", "card_status"),
        aliases=("customers", "customer"),
    ),
    EntitySpec(
        name="campaigns",
        bronze_table="campaigns_raw",
        silver_table="campaigns",
        ext_table="ext_campaigns",
        pk_column="campaign_id",
        silver_sql="sql/silver/campaigns.sql",
        columns=(
            "campaign_id",
            "merchant_id",
            "objective",
            "start_date",
            "end_date",
            "min_spend",
            "cashback_pct",
            "cashback_cap",
            "budget",
            "funding_type",
            "max_redemptions_per_customer",
            "status",
        ),
        aliases=("campaigns", "campaign"),
    ),
    EntitySpec(
        name="transactions",
        bronze_table="transactions_raw",
        silver_table="transactions",
        ext_table="ext_transactions",
        pk_column="txn_id",
        silver_sql="sql/silver/transactions.sql",
        columns=("txn_id", "customer_id", "merchant_id", "txn_ts", "amount", "txn_status"),
        ts_column="txn_ts",
        aliases=("transactions", "transaction"),
    ),
    EntitySpec(
        name="offer_sends",
        bronze_table="offer_sends_raw",
        silver_table="offer_sends",
        ext_table="ext_offer_sends",
        pk_column="send_id",
        silver_sql="sql/silver/offer_sends.sql",
        columns=("send_id", "campaign_id", "customer_id", "sent_at", "delivery_status", "channel"),
        ts_column="sent_at",
        aliases=("offer_sends", "offer_send"),
    ),
    EntitySpec(
        name="offer_redemptions",
        bronze_table="offer_redemptions_raw",
        silver_table="offer_redemptions",
        ext_table="ext_offer_redemptions",
        pk_column="redemption_id",
        silver_sql="sql/silver/offer_redemptions.sql",
        columns=(
            "redemption_id",
            "txn_id",
            "campaign_id",
            "customer_id",
            "awarded_cashback",
            "status",
            "awarded_at",
        ),
        ts_column="awarded_at",
        aliases=("offer_redemptions", "offer_redemption"),
    ),
    EntitySpec(
        name="customer_reviews",
        bronze_table="customer_reviews_raw",
        silver_table="customer_reviews",
        ext_table="ext_customer_reviews",
        pk_column="review_id",
        silver_sql="sql/silver/customer_reviews.sql",
        columns=(
            "review_id",
            "merchant_id",
            "review_date",
            "collected_at",
            "rating",
            "review_text",
            "source_ref",
        ),
        ts_column="collected_at",
        fallback_ts_column="review_date",
        aliases=("customer_reviews", "customer_review"),
    ),
    EntitySpec(
        name="merchant_feedback",
        bronze_table="merchant_feedback_raw",
        silver_table="merchant_feedback",
        ext_table="ext_merchant_feedback",
        pk_column="feedback_id",
        silver_sql="sql/silver/merchant_feedback.sql",
        columns=(
            "feedback_id",
            "merchant_id",
            "event_date",
            "recorded_at",
            "feedback_text",
            "source_ref",
            "verification_status",
        ),
        ts_column="recorded_at",
        fallback_ts_column="event_date",
        aliases=("merchant_feedback", "merchant_feedbacks"),
    ),
)

ENTITY_SPEC_MAP: Dict[str, EntitySpec] = {spec.name: spec for spec in ENTITY_SPECS}


def parse_timestamp_sql(col_expr: str) -> str:
    """Build a BigQuery TIMESTAMP parsing expression matching Silver layer formats."""
    trimmed = f"TRIM({col_expr})"
    return (
        "COALESCE("
        f"SAFE_CAST({trimmed} AS TIMESTAMP), "
        f"SAFE.PARSE_TIMESTAMP('%Y-%m-%d %H:%M:%S', {trimmed}, 'Asia/Kolkata'), "
        f"SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*SZ', {trimmed}), "
        f"SAFE.PARSE_TIMESTAMP('%Y-%m-%d', {trimmed}, 'Asia/Kolkata')"
        ")"
    )


def match_entity_for_uri(object_name_or_uri: str) -> Optional[str]:
    """Resolve a GCS CSV path/URI to one of the known medallion entity names.

    Matches longer/more specific aliases first so e.g. `merchant_feedback_*.csv`
    never collides with `merchants` or `customer_reviews_*.csv` with `customers`.
    """
    path_str = object_name_or_uri
    if path_str.startswith("gs://"):
        parts = path_str[5:].split("/", 1)
        path_str = parts[1] if len(parts) > 1 else ""

    pure_path = PurePosixPath(path_str)
    if pure_path.suffix.lower() != ".csv":
        return None

    stem = pure_path.stem.lower()
    parent_parts = [p.lower() for p in pure_path.parts[:-1]]

    # Sort all (alias, entity_name) pairs longest-first to avoid prefix collisions.
    alias_pairs: List[Tuple[str, str]] = []
    for spec in ENTITY_SPECS:
        for alias in spec.aliases or (spec.name,):
            alias_pairs.append((alias.lower(), spec.name))
    alias_pairs.sort(key=lambda item: len(item[0]), reverse=True)

    for alias, entity_name in alias_pairs:
        if stem == alias or re.match(rf"^{re.escape(alias)}[_\-.0-9].*$", stem):
            return entity_name

    for part in reversed(parent_parts):
        for alias, entity_name in alias_pairs:
            if part == alias:
                return entity_name

    return None


class WatermarkService:
    """Manages incremental high-watermarks, GCS ingestion ledger, and batch IDs."""

    def __init__(
        self,
        project_id: Optional[str] = None,
        bronze_dataset: Optional[str] = None,
        silver_dataset: Optional[str] = None,
        config: Optional[Any] = None,
    ):
        self.config = config or get_config()
        self.project_id = project_id or self.config.gcp.project_id
        self.bronze_dataset = bronze_dataset or getattr(self.config.gcp, "bronze_dataset", "offers_bronze")
        self.silver_dataset = silver_dataset or getattr(self.config.gcp, "silver_dataset", "offers_silver")

    @property
    def watermark_table(self) -> str:
        return f"{self.project_id}.{self.bronze_dataset}.pipeline_watermark"

    @property
    def ingestion_log_table(self) -> str:
        return f"{self.project_id}.{self.bronze_dataset}.gcs_ingestion_log"

    def generate_batch_id(self) -> str:
        """Generate a monotonic IST batch token: B_YYMMDD_HHMM."""
        return datetime.now(IST).strftime("B_%y%m%d_%H%M")

    def get_watermark(self, entity_name: str) -> Dict[str, Any]:
        """Fetch current high watermark and cumulative counters for an entity."""
        sql = f"""
        SELECT entity_name, last_batch_id, high_watermark,
               cumulative_rows_bronze, cumulative_rows_silver,
               cumulative_rows_rejected, last_discrepancy_count, last_updated
        FROM `{self.watermark_table}`
        WHERE entity_name = @entity
        LIMIT 1
        """
        params = [bigquery.ScalarQueryParameter("entity", "STRING", entity_name)]
        try:
            rows = execute_query(sql, parameters=params)
            return rows[0] if rows else {}
        except Exception as exc:
            logger.warning(f"Could not read watermark for {entity_name}: {exc}")
            return {}

    def get_all_watermarks(self) -> List[Dict[str, Any]]:
        """Fetch watermark rows for all tracked entities."""
        sql = f"""
        SELECT entity_name, last_batch_id, high_watermark,
               cumulative_rows_bronze, cumulative_rows_silver,
               cumulative_rows_rejected, last_discrepancy_count, last_updated
        FROM `{self.watermark_table}`
        ORDER BY entity_name
        """
        try:
            return execute_query(sql)
        except Exception as exc:
            logger.warning(f"Could not read pipeline watermarks: {exc}")
            return []

    def get_ingested_file_signatures(
        self,
        entity_type: Optional[str] = None,
    ) -> Dict[str, Tuple[Optional[str], Optional[int]]]:
        """Return latest (file_etag, gcs_generation_id) per file_uri with status='INGESTED'."""
        where_clause = "WHERE status = 'INGESTED'"
        params: List[bigquery.ScalarQueryParameter] = []
        if entity_type:
            where_clause += " AND entity_type = @entity_type"
            params.append(bigquery.ScalarQueryParameter("entity_type", "STRING", entity_type))

        sql = f"""
        SELECT file_uri, file_etag, gcs_generation_id
        FROM (
            SELECT
                file_uri,
                file_etag,
                gcs_generation_id,
                ROW_NUMBER() OVER (PARTITION BY file_uri ORDER BY ingested_at DESC) AS rn
            FROM `{self.ingestion_log_table}`
            {where_clause}
        )
        WHERE rn = 1
        """
        try:
            rows = execute_query(sql, parameters=params or None)
            signatures: Dict[str, Tuple[Optional[str], Optional[int]]] = {}
            for row in rows:
                gen = row.get("gcs_generation_id")
                signatures[row["file_uri"]] = (
                    row.get("file_etag"),
                    int(gen) if gen is not None else None,
                )
            return signatures
        except Exception as exc:
            logger.warning(f"Could not read gcs_ingestion_log signatures: {exc}")
            return {}

    def discover_delta_files(
        self,
        bucket_name: Optional[str] = None,
        prefix: Optional[str] = None,
        storage_client: Optional[Any] = None,
    ) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        """List GCS CSV blobs under raw_prefix and classify into new delta vs skipped files."""
        pipeline_cfg = getattr(self.config, "pipeline", None)
        storage_cfg = getattr(self.config, "storage", None)
        target_bucket = (
            bucket_name
            or getattr(pipeline_cfg, "raw_bucket", None)
            or getattr(storage_cfg, "bucket_name", None)
            or f"{self.project_id}-data"
        )
        target_prefix = (
            prefix
            if prefix is not None
            else getattr(pipeline_cfg, "raw_prefix", "raw_data/")
        )

        client = storage_client or get_storage_client(self.project_id)
        ingested_sigs = self.get_ingested_file_signatures()

        result: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
            spec.name: {"pending": [], "skipped": []} for spec in ENTITY_SPECS
        }

        blobs = client.list_blobs(target_bucket, prefix=target_prefix)
        for blob in blobs:
            entity_name = match_entity_for_uri(blob.name)
            if not entity_name:
                continue

            file_uri = f"gs://{target_bucket}/{blob.name}"
            file_etag = getattr(blob, "etag", None) or getattr(blob, "md5_hash", None)
            raw_gen = getattr(blob, "generation", None)
            gen_id = int(raw_gen) if raw_gen is not None else None
            updated = getattr(blob, "updated", None)
            updated_iso = updated.isoformat() if hasattr(updated, "isoformat") else updated

            file_info = {
                "file_uri": file_uri,
                "file_name": Path(blob.name).name,
                "entity_type": entity_name,
                "file_etag": file_etag,
                "gcs_generation_id": gen_id,
                "file_size_bytes": int(getattr(blob, "size", 0) or 0),
                "gcs_updated_time": updated_iso,
            }

            prev_sig = ingested_sigs.get(file_uri)
            if prev_sig is not None and prev_sig == (file_etag, gen_id):
                result[entity_name]["skipped"].append(file_info)
            else:
                result[entity_name]["pending"].append(file_info)

        return result

    def log_ingestion_event(
        self,
        file_info: Dict[str, Any],
        batch_id: str,
        status: str,
        row_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Insert a file ingestion ledger event into offers_bronze.gcs_ingestion_log."""
        sql = f"""
        INSERT INTO `{self.ingestion_log_table}` (
            file_uri, file_name, entity_type, file_etag, gcs_generation_id,
            file_size_bytes, gcs_updated_time, batch_id, status, row_count,
            error_message, ingested_at
        )
        VALUES (
            @file_uri, @file_name, @entity_type, @file_etag, @gcs_generation_id,
            @file_size_bytes, @gcs_updated_time, @batch_id, @status, @row_count,
            @error_message, CURRENT_TIMESTAMP()
        )
        """
        params = [
            bigquery.ScalarQueryParameter("file_uri", "STRING", file_info["file_uri"]),
            bigquery.ScalarQueryParameter("file_name", "STRING", file_info.get("file_name")),
            bigquery.ScalarQueryParameter("entity_type", "STRING", file_info.get("entity_type")),
            bigquery.ScalarQueryParameter("file_etag", "STRING", file_info.get("file_etag")),
            bigquery.ScalarQueryParameter("gcs_generation_id", "INT64", file_info.get("gcs_generation_id")),
            bigquery.ScalarQueryParameter("file_size_bytes", "INT64", file_info.get("file_size_bytes")),
            bigquery.ScalarQueryParameter("gcs_updated_time", "TIMESTAMP", file_info.get("gcs_updated_time")),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("row_count", "INT64", row_count),
            bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
        ]
        execute_query(sql, parameters=params)

    def update_ingestion_status(
        self,
        entity_type: str,
        batch_id: str,
        status: str,
        row_count: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        """Update PENDING ingestion log entries for an entity+batch to INGESTED or FAILED."""
        sql = f"""
        UPDATE `{self.ingestion_log_table}`
        SET
            status = @status,
            row_count = @row_count,
            error_message = @error_message,
            ingested_at = CURRENT_TIMESTAMP()
        WHERE entity_type = @entity_type
          AND batch_id = @batch_id
          AND status = 'PENDING'
        """
        params = [
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("row_count", "INT64", row_count),
            bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
            bigquery.ScalarQueryParameter("entity_type", "STRING", entity_type),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
        ]
        execute_query(sql, parameters=params)

    def compute_batch_reconciliation(
        self,
        entity_name: str,
        batch_id: str,
    ) -> Dict[str, Any]:
        """Compute batch-scoped Bronze/Silver/Rejected counts, BR-4 discrepancy, and max source timestamp."""
        spec = ENTITY_SPEC_MAP[entity_name]
        bronze_fqn = f"{self.project_id}.{self.bronze_dataset}.{spec.bronze_table}"
        silver_fqn = f"{self.project_id}.{self.silver_dataset}.{spec.silver_table}"
        invalid_fqn = f"{self.project_id}.{self.silver_dataset}.invalid_records"

        max_ts_expr = "CAST(NULL AS TIMESTAMP)"
        if spec.ts_column:
            if spec.fallback_ts_column:
                parsed = (
                    f"COALESCE({parse_timestamp_sql(spec.ts_column)}, "
                    f"{parse_timestamp_sql(spec.fallback_ts_column)})"
                )
            else:
                parsed = parse_timestamp_sql(spec.ts_column)
            max_ts_expr = f"MAX({parsed})"

        sql = f"""
        WITH b AS (
            SELECT COUNT(*) AS cnt, {max_ts_expr} AS max_ts
            FROM `{bronze_fqn}`
            WHERE batch_id = @batch_id
        ),
        s AS (
            SELECT COUNT(*) AS cnt
            FROM `{silver_fqn}`
            WHERE batch_id = @batch_id
        ),
        r AS (
            SELECT COUNT(*) AS cnt
            FROM `{invalid_fqn}`
            WHERE batch_id = @batch_id
              AND table_name = @bronze_table
        )
        SELECT
            b.cnt AS bronze_rows,
            s.cnt AS silver_rows,
            r.cnt AS rejected_rows,
            b.cnt - (s.cnt + r.cnt) AS discrepancy_count,
            b.max_ts AS max_source_ts
        FROM b, s, r
        """
        params = [
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("bronze_table", "STRING", spec.bronze_table),
        ]
        rows = execute_query(sql, parameters=params)
        if not rows:
            return {
                "bronze_rows": 0,
                "silver_rows": 0,
                "rejected_rows": 0,
                "discrepancy_count": 0,
                "max_source_ts": None,
            }
        return rows[0]

    def update_watermark(
        self,
        entity_name: str,
        batch_id: str,
        high_watermark: Optional[str],
        batch_bronze_rows: int,
        batch_silver_rows: int,
        batch_rejected_rows: int,
        discrepancy_count: int = 0,
    ) -> None:
        """Atomically upsert entity high-watermark and cumulative BR-4 counts."""
        sql = f"""
        MERGE `{self.watermark_table}` T
        USING (
            SELECT
                @entity_name AS entity_name,
                @batch_id AS last_batch_id,
                @high_watermark AS high_watermark,
                @batch_bronze AS batch_bronze,
                @batch_silver AS batch_silver,
                @batch_rejected AS batch_rejected,
                @discrepancy AS discrepancy
        ) S
        ON T.entity_name = S.entity_name
        WHEN MATCHED THEN
            UPDATE SET
                last_batch_id = S.last_batch_id,
                high_watermark = COALESCE(
                    GREATEST(T.high_watermark, S.high_watermark),
                    S.high_watermark,
                    T.high_watermark
                ),
                cumulative_rows_bronze = COALESCE(T.cumulative_rows_bronze, 0) + S.batch_bronze,
                cumulative_rows_silver = COALESCE(T.cumulative_rows_silver, 0) + S.batch_silver,
                cumulative_rows_rejected = COALESCE(T.cumulative_rows_rejected, 0) + S.batch_rejected,
                last_discrepancy_count = S.discrepancy,
                last_updated = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN
            INSERT (
                entity_name, last_batch_id, high_watermark,
                cumulative_rows_bronze, cumulative_rows_silver,
                cumulative_rows_rejected, last_discrepancy_count, last_updated
            )
            VALUES (
                S.entity_name, S.last_batch_id, S.high_watermark,
                S.batch_bronze, S.batch_silver,
                S.batch_rejected, S.discrepancy, CURRENT_TIMESTAMP()
            )
        """
        params = [
            bigquery.ScalarQueryParameter("entity_name", "STRING", entity_name),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("high_watermark", "TIMESTAMP", high_watermark),
            bigquery.ScalarQueryParameter("batch_bronze", "INT64", batch_bronze_rows),
            bigquery.ScalarQueryParameter("batch_silver", "INT64", batch_silver_rows),
            bigquery.ScalarQueryParameter("batch_rejected", "INT64", batch_rejected_rows),
            bigquery.ScalarQueryParameter("discrepancy", "INT64", discrepancy_count),
        ]
        execute_query(sql, parameters=params)
