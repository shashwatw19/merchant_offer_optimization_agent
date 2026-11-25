"""Incremental Bronze & Silver pipeline runner driven by GCS ledger and high-watermarks."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from google.cloud import bigquery

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from pipeline.watermark_service import (
    ENTITY_SPEC_MAP,
    ENTITY_SPECS,
    EntitySpec,
    IST,
    WatermarkService,
    parse_timestamp_sql,
)


def _format_ingestion_ts_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")


def _parse_ts_for_spec(spec: EntitySpec) -> Optional[str]:
    if not spec.ts_column:
        return None
    if spec.fallback_ts_column:
        return (
            f"COALESCE({parse_timestamp_sql(spec.ts_column)}, "
            f"{parse_timestamp_sql(spec.fallback_ts_column)})"
        )
    return parse_timestamp_sql(spec.ts_column)


def build_bronze_load_sql(
    spec: EntitySpec,
    delta_uris: Sequence[str],
    project_id: str,
    bronze_dataset: str,
    high_watermark: Optional[str] = None,
    enforce_row_watermark: bool = True,
) -> Tuple[str, List[bigquery.ScalarQueryParameter]]:
    """Build parameterized BigQuery SQL to load only new delta CSV URIs into Bronze."""
    if not delta_uris:
        raise ValueError(f"delta_uris must not be empty for entity '{spec.name}'")

    ext_fqn = f"{project_id}.{bronze_dataset}.{spec.ext_table}"
    raw_fqn = f"{project_id}.{bronze_dataset}.{spec.bronze_table}"

    ext_cols_ddl = ",\n    ".join(f"{col} STRING" for col in spec.columns)
    raw_cols_ddl = ",\n    ".join(
        [f"{col} STRING" for col in spec.columns] + ["batch_id STRING", "ingestion_ts STRING"]
    )
    insert_cols = ",\n    ".join([*spec.columns, "batch_id", "ingestion_ts"])
    select_cols = ",\n    ".join(
        [f"CAST({col} AS STRING)" for col in spec.columns] + ["@batch_id", "@ingestion_ts"]
    )
    uris_literal = ", ".join(f"'{uri}'" for uri in delta_uris)

    where_clause = ""
    params: List[bigquery.ScalarQueryParameter] = []
    ts_expr = _parse_ts_for_spec(spec)
    if enforce_row_watermark and ts_expr and high_watermark:
        # Preserve unparseable timestamps so Silver quarantines them per BR-4 conservation.
        where_clause = f"\nWHERE ({ts_expr} IS NULL OR {ts_expr} > @high_watermark)"
        params.append(bigquery.ScalarQueryParameter("high_watermark", "TIMESTAMP", high_watermark))

    sql = f"""CREATE OR REPLACE EXTERNAL TABLE `{ext_fqn}`
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
FROM `{ext_fqn}`{where_clause};
"""
    return sql, params


def _count_bronze_batch_rows(
    project_id: str,
    bronze_dataset: str,
    bronze_table: str,
    batch_id: str,
) -> int:
    sql = f"""
    SELECT COUNT(*) AS cnt
    FROM `{project_id}.{bronze_dataset}.{bronze_table}`
    WHERE batch_id = @batch_id
    """
    rows = execute_query(sql, parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)])
    return int(rows[0]["cnt"]) if rows else 0


def _resolve_specs(entities: Optional[Sequence[str]] = None) -> List[EntitySpec]:
    if not entities:
        return list(ENTITY_SPECS)
    requested = set(entities)
    unknown = requested - set(ENTITY_SPEC_MAP)
    if unknown:
        raise ValueError(f"Unknown entity name(s): {sorted(unknown)}")
    return [spec for spec in ENTITY_SPECS if spec.name in requested]


def run_bronze_incremental(
    batch_id: Optional[str] = None,
    entities: Optional[Sequence[str]] = None,
    enforce_row_watermark: Optional[bool] = None,
    dry_run: bool = False,
    watermark_service: Optional[WatermarkService] = None,
    storage_client: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Discover unseen GCS delta CSVs and load only new records into Bronze."""
    config = get_config()
    wm = watermark_service or WatermarkService(config=config)
    eff_batch_id = batch_id or wm.generate_batch_id()
    ingestion_ts = _format_ingestion_ts_ist()

    if enforce_row_watermark is None:
        pipeline_cfg = getattr(config, "pipeline", None)
        enforce_row_watermark = bool(getattr(pipeline_cfg, "enforce_row_watermark", True))

    discovered = wm.discover_delta_files(storage_client=storage_client)
    specs = _resolve_specs(entities)
    results: List[Dict[str, Any]] = []

    for spec in specs:
        entity_files = discovered.get(spec.name, {"pending": [], "skipped": []})
        pending = entity_files["pending"]
        skipped = entity_files["skipped"]

        if not pending:
            logger.info(
                f"[Bronze][{spec.name}] No new delta CSV files found "
                f"(skipped={len(skipped)} already ingested)."
            )
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": eff_batch_id,
                    "status": "SKIPPED",
                    "files": 0,
                    "skipped_files": len(skipped),
                    "rows": 0,
                }
            )
            continue

        uris = [item["file_uri"] for item in pending]
        if dry_run:
            logger.info(f"[Bronze][{spec.name}] DRY RUN would ingest {len(uris)} file(s): {uris}")
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": eff_batch_id,
                    "status": "DRY_RUN",
                    "files": len(uris),
                    "uris": uris,
                    "rows": 0,
                }
            )
            continue

        for file_info in pending:
            wm.log_ingestion_event(file_info, batch_id=eff_batch_id, status="PENDING")

        try:
            current_wm = wm.get_watermark(spec.name)
            high_wm = current_wm.get("high_watermark")
            sql, extra_params = build_bronze_load_sql(
                spec=spec,
                delta_uris=uris,
                project_id=wm.project_id,
                bronze_dataset=wm.bronze_dataset,
                high_watermark=high_wm,
                enforce_row_watermark=enforce_row_watermark,
            )
            params = [
                bigquery.ScalarQueryParameter("batch_id", "STRING", eff_batch_id),
                bigquery.ScalarQueryParameter("ingestion_ts", "STRING", ingestion_ts),
                *extra_params,
            ]
            execute_query(sql, parameters=params, timeout_sec=120.0)

            loaded_rows = _count_bronze_batch_rows(
                wm.project_id, wm.bronze_dataset, spec.bronze_table, eff_batch_id
            )
            if loaded_rows == 0:
                wm.update_ingestion_status(
                    spec.name,
                    eff_batch_id,
                    status="SKIPPED",
                    row_count=0,
                    error_message="0 rows exceeded high_watermark",
                )

            logger.info(
                f"[Bronze][{spec.name}] Loaded {loaded_rows} delta row(s) "
                f"from {len(uris)} file(s) for batch {eff_batch_id}."
            )
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": eff_batch_id,
                    "status": "LOADED" if loaded_rows > 0 else "SKIPPED",
                    "files": len(uris),
                    "skipped_files": len(skipped),
                    "rows": loaded_rows,
                }
            )
        except Exception as exc:
            logger.error(f"[Bronze][{spec.name}] Failed incremental load: {exc}")
            wm.update_ingestion_status(
                spec.name, eff_batch_id, status="FAILED", row_count=0, error_message=str(exc)
            )
            raise

    return results


def run_silver_incremental(
    batch_id: str,
    entities: Optional[Sequence[str]] = None,
    dry_run: bool = False,
    watermark_service: Optional[WatermarkService] = None,
    project_root: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Run batch-scoped Silver transformations in topological order and commit watermarks."""
    config = get_config()
    wm = watermark_service or WatermarkService(config=config)
    root = project_root or PROJECT_ROOT
    specs = _resolve_specs(entities)
    results: List[Dict[str, Any]] = []

    for spec in specs:
        bronze_rows = _count_bronze_batch_rows(
            wm.project_id, wm.bronze_dataset, spec.bronze_table, batch_id
        )
        if bronze_rows == 0:
            logger.info(f"[Silver][{spec.name}] 0 Bronze rows for batch {batch_id}; skipping.")
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": batch_id,
                    "status": "SKIPPED",
                    "bronze_rows": 0,
                    "silver_rows": 0,
                    "rejected_rows": 0,
                    "discrepancy_count": 0,
                }
            )
            continue

        if dry_run:
            logger.info(f"[Silver][{spec.name}] DRY RUN would process {bronze_rows} Bronze row(s).")
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": batch_id,
                    "status": "DRY_RUN",
                    "bronze_rows": bronze_rows,
                }
            )
            continue

        sql_path = root / spec.silver_sql
        sql_text = sql_path.read_text(encoding="utf-8")

        try:
            execute_query(
                sql_text,
                parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)],
                timeout_sec=120.0,
            )

            recon = wm.compute_batch_reconciliation(spec.name, batch_id)
            wm.update_watermark(
                entity_name=spec.name,
                batch_id=batch_id,
                high_watermark=recon.get("max_source_ts"),
                batch_bronze_rows=int(recon.get("bronze_rows", 0)),
                batch_silver_rows=int(recon.get("silver_rows", 0)),
                batch_rejected_rows=int(recon.get("rejected_rows", 0)),
                discrepancy_count=int(recon.get("discrepancy_count", 0)),
            )
            wm.update_ingestion_status(
                entity_type=spec.name,
                batch_id=batch_id,
                status="INGESTED",
                row_count=int(recon.get("bronze_rows", 0)),
            )

            logger.info(
                f"[Silver][{spec.name}] Batch {batch_id}: bronze={recon['bronze_rows']}, "
                f"silver={recon['silver_rows']}, rejected={recon['rejected_rows']}, "
                f"discrepancy={recon['discrepancy_count']}, high_watermark={recon['max_source_ts']}"
            )
            results.append(
                {
                    "entity": spec.name,
                    "batch_id": batch_id,
                    "status": "COMMITTED",
                    **recon,
                }
            )
        except Exception as exc:
            logger.error(f"[Silver][{spec.name}] Failed for batch {batch_id}: {exc}")
            wm.update_ingestion_status(
                entity_type=spec.name,
                batch_id=batch_id,
                status="FAILED",
                row_count=0,
                error_message=str(exc),
            )
            raise

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incremental Medallion Pipeline Runner with GCS Ledger & High-Watermark."
    )
    parser.add_argument(
        "--stage",
        choices=["bronze", "silver", "all"],
        default="all",
        help="Pipeline stage(s) to execute.",
    )
    parser.add_argument("--batch-id", type=str, default=None, help="Unified batch ID (B_YYMMDD_HHMM).")
    parser.add_argument(
        "--entities",
        nargs="*",
        default=None,
        help="Optional subset of entities to process.",
    )
    parser.add_argument(
        "--no-row-watermark",
        action="store_true",
        help="Disable row-level high_watermark filter in Bronze (rely only on GCS file ledger).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Discover delta files without writing.")
    args = parser.parse_args()

    wm = WatermarkService()
    batch_id = args.batch_id or wm.generate_batch_id()
    enforce_row = False if args.no_row_watermark else None

    if args.stage in ("bronze", "all"):
        run_bronze_incremental(
            batch_id=batch_id,
            entities=args.entities,
            enforce_row_watermark=enforce_row,
            dry_run=args.dry_run,
            watermark_service=wm,
        )

    if args.stage in ("silver", "all"):
        run_silver_incremental(
            batch_id=batch_id,
            entities=args.entities,
            dry_run=args.dry_run,
            watermark_service=wm,
        )


if __name__ == "__main__":
    main()
