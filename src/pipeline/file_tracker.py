"""Folder-based GCS CSV loader that tracks the latest loaded file timestamp per entity."""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple
from dataclasses import dataclass

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from services.gcs_storage import get_storage_client

IST = timezone(timedelta(hours=5, minutes=30))

_TS_PATTERNS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(\d{4}-\d{2}-\d{2}[T_ -]\d{2}[:-]\d{2}[:-]\d{2})"), "iso_dt"),
    (re.compile(r"(\d{8}_\d{6})"), "%Y%m%d_%H%M%S"),
    (re.compile(r"(\d{14})"), "%Y%m%d%H%M%S"),
    (re.compile(r"(\d{4}-\d{2}-\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(\d{8})"), "%Y%m%d"),
)


@dataclass(frozen=True)
class EntityFolderSpec:
    """Metadata for a raw GCS entity folder and its Bronze target table."""

    name: str
    folder: str
    bronze_table: str
    ext_table: str
    pk_column: str
    columns: Tuple[str, ...]
    fk_defs: Tuple[Tuple[str, str, str, str], ...] = ()
    # fk_defs tuple: (constraint_name, local_col, ref_bronze_table, ref_col)


ENTITY_FOLDER_SPECS: Tuple[EntityFolderSpec, ...] = (
    EntityFolderSpec(
        name="merchants",
        folder="merchants",
        bronze_table="merchants_raw",
        ext_table="ext_merchants",
        pk_column="merchant_id",
        columns=("merchant_id", "name", "category", "city", "status"),
    ),
    EntityFolderSpec(
        name="customers",
        folder="customers",
        bronze_table="customers_raw",
        ext_table="ext_customers",
        pk_column="customer_id",
        columns=(
            "customer_id",
            "city",
            "segment",
            "email",
            "phone",
            "account_number",
            "marketing_eligible",
            "card_status",
        ),
    ),
    EntityFolderSpec(
        name="campaigns",
        folder="campaigns",
        bronze_table="campaigns_raw",
        ext_table="ext_campaigns",
        pk_column="campaign_id",
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
        fk_defs=(("fk_bronze_campaigns_merchant", "merchant_id", "merchants_raw", "merchant_id"),),
    ),
    EntityFolderSpec(
        name="transactions",
        folder="transactions",
        bronze_table="transactions_raw",
        ext_table="ext_transactions",
        pk_column="txn_id",
        columns=(
            "txn_id",
            "customer_id",
            "merchant_id",
            "card_number",
            "account_number",
            "txn_ts",
            "amount",
            "txn_status",
        ),
        fk_defs=(
            ("fk_bronze_transactions_customer", "customer_id", "customers_raw", "customer_id"),
            ("fk_bronze_transactions_merchant", "merchant_id", "merchants_raw", "merchant_id"),
        ),
    ),
    EntityFolderSpec(
        name="offer_sends",
        folder="offer_sends",
        bronze_table="offer_sends_raw",
        ext_table="ext_offer_sends",
        pk_column="send_id",
        columns=("send_id", "campaign_id", "customer_id", "sent_at", "delivery_status", "channel"),
        fk_defs=(
            ("fk_bronze_offer_sends_campaign", "campaign_id", "campaigns_raw", "campaign_id"),
            ("fk_bronze_offer_sends_customer", "customer_id", "customers_raw", "customer_id"),
        ),
    ),
    EntityFolderSpec(
        name="offer_redemptions",
        folder="offer_redemptions",
        bronze_table="offer_redemptions_raw",
        ext_table="ext_offer_redemptions",
        pk_column="redemption_id",
        columns=(
            "redemption_id",
            "txn_id",
            "campaign_id",
            "customer_id",
            "awarded_cashback",
            "status",
            "awarded_at",
        ),
        fk_defs=(
            ("fk_bronze_offer_redemptions_txn", "txn_id", "transactions_raw", "txn_id"),
            ("fk_bronze_offer_redemptions_campaign", "campaign_id", "campaigns_raw", "campaign_id"),
            ("fk_bronze_offer_redemptions_customer", "customer_id", "customers_raw", "customer_id"),
        ),
    ),
    EntityFolderSpec(
        name="customer_reviews",
        folder="customer_reviews",
        bronze_table="customer_reviews_raw",
        ext_table="ext_customer_reviews",
        pk_column="review_id",
        columns=("review_id", "merchant_id", "review_date", "collected_at", "rating", "review_text", "source_ref"),
        fk_defs=(("fk_bronze_customer_reviews_merchant", "merchant_id", "merchants_raw", "merchant_id"),),
    ),
    EntityFolderSpec(
        name="merchant_feedback",
        folder="merchant_feedback",
        bronze_table="merchant_feedback_raw",
        ext_table="ext_merchant_feedback",
        pk_column="feedback_id",
        columns=(
            "feedback_id",
            "merchant_id",
            "event_date",
            "recorded_at",
            "feedback_text",
            "source_ref",
            "verification_status",
        ),
        fk_defs=(("fk_bronze_merchant_feedback_merchant", "merchant_id", "merchants_raw", "merchant_id"),),
    ),
)

ENTITY_FOLDER_MAP: Dict[str, EntityFolderSpec] = {spec.name: spec for spec in ENTITY_FOLDER_SPECS}


def _normalize_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def extract_file_timestamp(blob_name: str, blob_updated: Optional[datetime] = None) -> Optional[datetime]:
    """Extract UTC timestamp from a CSV filename, falling back to GCS blob.updated."""
    file_name = PurePosixPath(blob_name).name
    for pattern, fmt in _TS_PATTERNS:
        match = pattern.search(file_name)
        if not match:
            continue
        raw_val = match.group(1)
        try:
            if fmt == "iso_dt":
                normalized = re.sub(r"[T_ ]", " ", raw_val)
                date_part, time_part = normalized.split(" ", 1)
                time_part = time_part.replace("-", ":")
                parsed = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S")
            else:
                parsed = datetime.strptime(raw_val, fmt)
            return _normalize_utc(parsed)
        except ValueError:
            continue

    if blob_updated is not None:
        return _normalize_utc(blob_updated)
    return None


def build_bronze_load_sql(
    spec: EntityFolderSpec,
    file_uris: Sequence[str],
    project_id: str,
    bronze_dataset: str,
) -> str:
    """Build BigQuery SQL to load the given GCS CSV URIs into Bronze with PK/FK DDL."""
    if not file_uris:
        raise ValueError(f"file_uris must not be empty for entity '{spec.name}'")

    ext_fqn = f"{project_id}.{bronze_dataset}.{spec.ext_table}"
    raw_fqn = f"{project_id}.{bronze_dataset}.{spec.bronze_table}"

    ext_cols_ddl = ",\n    ".join(f"{col} STRING" for col in spec.columns)
    table_items = [f"{col} STRING" for col in spec.columns] + [
        "batch_id STRING",
        "ingestion_ts STRING",
        f"PRIMARY KEY ({spec.pk_column}) NOT ENFORCED",
    ]
    for fk_name, local_col, ref_table, ref_col in spec.fk_defs:
        ref_fqn = f"{project_id}.{bronze_dataset}.{ref_table}"
        table_items.append(
            f"CONSTRAINT {fk_name} FOREIGN KEY ({local_col}) REFERENCES `{ref_fqn}`({ref_col}) NOT ENFORCED"
        )
    raw_cols_ddl = ",\n    ".join(table_items)

    insert_cols = ",\n    ".join([*spec.columns, "batch_id", "ingestion_ts"])
    select_cols = ",\n    ".join(
        [f"CAST({col} AS STRING)" for col in spec.columns] + ["@batch_id", "@ingestion_ts"]
    )
    uris_literal = ", ".join(f"'{uri}'" for uri in file_uris)

    return f"""CREATE OR REPLACE EXTERNAL TABLE `{ext_fqn}`
(
    {ext_cols_ddl}
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = [{uris_literal}]
);

CREATE TABLE IF NOT EXISTS `{raw_fqn}`
(
    {raw_cols_ddl}
);

INSERT INTO `{raw_fqn}`
(
    {insert_cols}
)
SELECT
    {select_cols}
FROM `{ext_fqn}`;

DROP EXTERNAL TABLE IF EXISTS `{ext_fqn}`;
"""


class FileTrackerService:
    """Discovers new timestamped CSVs per entity folder and updates file_load_tracker."""

    def __init__(self, config: Optional[Any] = None, project_id: Optional[str] = None):
        self.config = config or get_config()
        self.project_id = project_id or self.config.gcp.project_id
        self.bronze_dataset = getattr(self.config.gcp, "bronze_dataset", "offers_bronze")
        pipeline_cfg = getattr(self.config, "pipeline", None)
        storage_cfg = getattr(self.config, "storage", None)
        self.raw_bucket = getattr(pipeline_cfg, "raw_bucket", None) or getattr(
            storage_cfg, "bucket_name", "prj-imp-act-campaign-data"
        )
        raw_prefix = getattr(pipeline_cfg, "raw_prefix", "raw_data/")
        self.raw_prefix = raw_prefix.rstrip("/") + "/" if raw_prefix else ""

    @property
    def tracker_table(self) -> str:
        return f"{self.project_id}.{self.bronze_dataset}.file_load_tracker"

    @staticmethod
    def generate_batch_id() -> str:
        return datetime.now(IST).strftime("B_%y%m%d_%H%M")

    def get_last_timestamp(self, entity_name: str) -> Optional[datetime]:
        sql = f"""
        SELECT last_file_timestamp
        FROM `{self.tracker_table}`
        WHERE entity_name = @entity_name
        LIMIT 1
        """
        params = [bigquery.ScalarQueryParameter("entity_name", "STRING", entity_name)]
        try:
            rows = execute_query(sql, parameters=params)
        except Exception as exc:
            logger.warning(f"Could not read file_load_tracker for {entity_name}: {exc}")
            return None

        if not rows or rows[0].get("last_file_timestamp") is None:
            return None
        val = rows[0]["last_file_timestamp"]
        if isinstance(val, str):
            val = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return _normalize_utc(val)

    def discover_new_files(
        self,
        spec: EntityFolderSpec,
        storage_client: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """List CSVs in gs://<bucket>/<raw_prefix><folder>/ newer than last_file_timestamp."""
        client = storage_client or get_storage_client(project_id=self.project_id)
        folder_prefix = f"{self.raw_prefix}{spec.folder}/"
        last_ts = self.get_last_timestamp(spec.name)

        new_files: List[Dict[str, Any]] = []
        for blob in client.list_blobs(self.raw_bucket, prefix=folder_prefix):
            if blob.name.endswith("/") or not blob.name.lower().endswith(".csv"):
                continue
            file_ts = extract_file_timestamp(blob.name, getattr(blob, "updated", None))
            if file_ts is None:
                logger.warning(f"[{spec.name}] Skipping '{blob.name}': no timestamp found.")
                continue
            if last_ts is not None and file_ts <= last_ts:
                continue
            new_files.append(
                {
                    "file_uri": f"gs://{self.raw_bucket}/{blob.name}",
                    "file_name": PurePosixPath(blob.name).name,
                    "file_timestamp": file_ts,
                }
            )

        new_files.sort(key=lambda item: (item["file_timestamp"], item["file_name"]))
        return new_files

    def update_tracker(
        self,
        entity_name: str,
        last_loaded_file: str,
        last_file_timestamp: datetime,
        batch_id: str,
        rows_loaded: int,
    ) -> None:
        sql = f"""
        MERGE `{self.tracker_table}` T
        USING (
            SELECT
                @entity_name AS entity_name,
                @last_loaded_file AS last_loaded_file,
                @last_file_timestamp AS last_file_timestamp,
                @last_batch_id AS last_batch_id,
                @rows_loaded AS rows_loaded,
                CURRENT_TIMESTAMP() AS updated_at
        ) S
        ON T.entity_name = S.entity_name
        WHEN MATCHED THEN
            UPDATE SET
                last_loaded_file = S.last_loaded_file,
                last_file_timestamp = S.last_file_timestamp,
                last_batch_id = S.last_batch_id,
                rows_loaded = S.rows_loaded,
                updated_at = S.updated_at
        WHEN NOT MATCHED THEN
            INSERT (entity_name, last_loaded_file, last_file_timestamp, last_batch_id, rows_loaded, updated_at)
            VALUES (S.entity_name, S.last_loaded_file, S.last_file_timestamp, S.last_batch_id, S.rows_loaded, S.updated_at)
        """
        params = [
            bigquery.ScalarQueryParameter("entity_name", "STRING", entity_name),
            bigquery.ScalarQueryParameter("last_loaded_file", "STRING", last_loaded_file),
            bigquery.ScalarQueryParameter(
                "last_file_timestamp", "TIMESTAMP", _normalize_utc(last_file_timestamp).isoformat()
            ),
            bigquery.ScalarQueryParameter("last_batch_id", "STRING", batch_id),
            bigquery.ScalarQueryParameter("rows_loaded", "INT64", int(rows_loaded)),
        ]
        execute_query(sql, parameters=params)


def _count_batch_rows(project_id: str, bronze_dataset: str, bronze_table: str, batch_id: str) -> int:
    sql = f"""
    SELECT COUNT(*) AS cnt
    FROM `{project_id}.{bronze_dataset}.{bronze_table}`
    WHERE batch_id = @batch_id
    """
    rows = execute_query(sql, parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)])
    return int(rows[0]["cnt"]) if rows else 0


def _resolve_specs(entities: Optional[Sequence[str]] = None) -> List[EntityFolderSpec]:
    if not entities:
        return list(ENTITY_FOLDER_SPECS)
    requested = set(entities)
    unknown = requested - set(ENTITY_FOLDER_MAP)
    if unknown:
        raise ValueError(f"Unknown entity name(s): {sorted(unknown)}")
    return [spec for spec in ENTITY_FOLDER_SPECS if spec.name in requested]


def run_bronze_load(
    batch_id: Optional[str] = None,
    entities: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    tracker_service: Optional[FileTrackerService] = None,
    storage_client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Load only new timestamped CSV files from each raw entity folder into Bronze."""
    tracker = tracker_service or FileTrackerService()
    eff_batch_id = batch_id or tracker.generate_batch_id()
    ingestion_ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
    results: List[Dict[str, Any]] = []

    for spec in _resolve_specs(entities):
        new_files = tracker.discover_new_files(spec, storage_client=storage_client)
        if not new_files:
            logger.info(f"[Bronze][{spec.name}] No new CSV files in '{spec.folder}/'; skipping.")
            results.append({"entity": spec.name, "batch_id": eff_batch_id, "status": "SKIPPED", "files": 0, "rows": 0})
            continue

        uris = [item["file_uri"] for item in new_files]
        latest = new_files[-1]
        if dry_run:
            logger.info(f"[Bronze][{spec.name}] DRY RUN would load {len(uris)} file(s): {uris}")
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": eff_batch_id,
                    "status": "DRY_RUN",
                    "files": len(uris),
                    "uris": uris,
                    "latest_timestamp": latest["file_timestamp"].isoformat(),
                }
            )
            continue

        sql = build_bronze_load_sql(
            spec=spec,
            file_uris=uris,
            project_id=tracker.project_id,
            bronze_dataset=tracker.bronze_dataset,
        )
        params = [
            bigquery.ScalarQueryParameter("batch_id", "STRING", eff_batch_id),
            bigquery.ScalarQueryParameter("ingestion_ts", "STRING", ingestion_ts),
        ]
        execute_query(sql, parameters=params, timeout_sec=120.0)

        rows_loaded = _count_batch_rows(tracker.project_id, tracker.bronze_dataset, spec.bronze_table, eff_batch_id)
        tracker.update_tracker(
            entity_name=spec.name,
            last_loaded_file=latest["file_uri"],
            last_file_timestamp=latest["file_timestamp"],
            batch_id=eff_batch_id,
            rows_loaded=rows_loaded,
        )

        logger.info(
            f"[Bronze][{spec.name}] Loaded {rows_loaded} row(s) from {len(uris)} file(s); "
            f"tracker updated to {latest['file_timestamp'].isoformat()}."
        )
        results.append(
            {
                "entity": spec.name,
                "batch_id": eff_batch_id,
                "status": "LOADED",
                "files": len(uris),
                "rows": rows_loaded,
                "latest_file": latest["file_uri"],
                "latest_timestamp": latest["file_timestamp"].isoformat(),
            }
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Load new timestamped CSVs per entity folder into Bronze.")
    parser.add_argument("--batch-id", type=str, default=None, help="Batch ID (B_YYMMDD_HHMM).")
    parser.add_argument("--entities", nargs="*", default=None, help="Optional subset of entities.")
    parser.add_argument("--dry-run", action="store_true", help="Discover new files without loading.")
    args = parser.parse_args()
    run_bronze_load(batch_id=args.batch_id, entities=args.entities, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
