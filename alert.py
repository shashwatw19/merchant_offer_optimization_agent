import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Set

# Ensure src is on sys.path
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from core.time_utils import now_ist, now_ist_str
from domain.rules import get_rule_queries, parse_alert_row


def get_active_alert_ids(project_id: str, cooldown_minutes: float = 2.0) -> Set[str]:
    """Retrieve alert IDs that are currently active (OPEN, PROCESSING) or in RESOLVED cooldown (default: 2 mins)."""
    config = get_config()
    table_id = f"{project_id}.{config.gcp.gold_dataset}.alerts"
    sql = f"""
        SELECT alert_id, status, created_at, resolved_at
        FROM `{table_id}`
        WHERE status IN ('OPEN', 'PROCESSING', 'RESOLVED')
    """
    try:
        rows = bq_client.execute_query(sql)
        active_ids = set()
        current_ist_dt = now_ist().replace(tzinfo=None)

        for r in rows:
            aid = r.get("alert_id")
            st = (r.get("status") or "").upper()
            if not aid:
                continue

            # Always suppress if alert is currently open or being processed
            if st in ("OPEN", "PROCESSING"):
                active_ids.add(aid)
            elif st == "RESOLVED":
                # Check resolved cooldown window (default: 2 minutes)
                resolved_str = r.get("resolved_at")
                if not resolved_str:
                    active_ids.add(aid)
                    continue

                try:
                    clean_ts = resolved_str.replace(" IST", "").strip()
                    if "T" in clean_ts:
                        res_dt = datetime.fromisoformat(clean_ts)
                    else:
                        res_dt = datetime.strptime(clean_ts[:19], "%Y-%m-%d %H:%M:%S")

                    diff_minutes = (current_ist_dt - res_dt).total_seconds() / 60.0
                    if diff_minutes < cooldown_minutes:
                        active_ids.add(aid)
                except Exception:
                    # In case of unparseable timestamp, conservatively treat as active
                    active_ids.add(aid)

        return active_ids
    except Exception as exc:
        logger.debug(f"Could not query existing alerts (table might be empty or new): {exc}")
        return set()


def run_rule_alerts(rule_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Execute a single alert rule query and return standardized alert payloads with IST timestamps."""
    queries = get_rule_queries(project_id)
    if rule_id not in queries:
        logger.error(f"Unknown rule ID '{rule_id}'. Allowed: {list(queries.keys())}")
        return []

    sql = queries[rule_id]
    logger.info(f"Evaluating rule {rule_id} in BigQuery...")
    try:
        rows = bq_client.execute_query(sql)
        alerts = [parse_alert_row(row) for row in rows]
        # Guarantee created_at is populated in IST format
        for a in alerts:
            if not a.get("created_at"):
                a["created_at"] = now_ist_str()
        logger.info(f"Rule {rule_id} triggered {len(alerts)} alert(s).")
        return alerts
    except Exception as exc:
        logger.error(f"Failed executing query for rule {rule_id}: {exc}")
        return []


def run_all_alerts(
    project_id: str,
    selected_rule: str = None,
    filter_active: bool = True,
    cooldown_minutes: float = None,
) -> List[Dict[str, Any]]:
    """Execute alert rules and filter out duplicate alerts that are already OPEN, PROCESSING, or recently RESOLVED."""
    config = get_config()
    eff_cooldown = cooldown_minutes
    if eff_cooldown is None:
        eff_cooldown = float(getattr(getattr(config, "investigation", None), "alert_cooldown_minutes", 2.0))

    rules_to_run = [selected_rule] if selected_rule else ["R1", "R2", "R3"]
    all_alerts = []

    for rule_id in rules_to_run:
        rule_alerts = run_rule_alerts(rule_id, project_id)
        all_alerts.extend(rule_alerts)

    if not filter_active or not all_alerts:
        return all_alerts

    # Deduplicate against existing alerts in BigQuery
    active_ids = get_active_alert_ids(project_id, cooldown_minutes=eff_cooldown)
    if not active_ids:
        return all_alerts

    filtered_alerts = []
    for a in all_alerts:
        aid = a["alert_id"]
        if aid in active_ids:
            logger.info(
                f"Suppressed alert {aid} ({a.get('rule_id')}, {a.get('campaign_id')}): "
                f"already active or in {eff_cooldown}m cooldown window."
            )
        else:
            filtered_alerts.append(a)

    return filtered_alerts


def save_alerts_to_bigquery(alerts: List[Dict[str, Any]], project_id: str) -> None:
    """Insert triggered alerts into BigQuery offers_gold.alerts table via batch load job."""
    if not alerts:
        return

    config = get_config()
    table_id = f"{project_id}.{config.gcp.gold_dataset}.alerts"
    client = bq_client.get_bigquery_client(project_id)

    # Ensure all timestamps are in IST
    current_time_ist = now_ist_str()
    for a in alerts:
        if not a.get("created_at"):
            a["created_at"] = current_time_ist

    try:
        # Batch load job commits directly into storage, avoiding streaming buffer locks
        job = client.load_table_from_json(alerts, table_id)
        job.result(timeout=30.0)
        logger.info(f"Successfully inserted {len(alerts)} alerts into `{table_id}` via load job.")
    except Exception as exc:
        logger.warning(f"Batch load job failed ({exc}), falling back to streaming insert...")
        errors = client.insert_rows_json(table_id, alerts)
        if errors:
            logger.error(f"BigQuery alert insertion failed: {errors}")
            raise RuntimeError(f"BigQuery insert failed: {errors}") from exc
        logger.info(f"Successfully inserted {len(alerts)} alerts into `{table_id}` via streaming insert.")


def main() -> None:
    config = get_config()

    parser = argparse.ArgumentParser(
        description="Deterministic alert detection engine for merchant offer optimization with IST timestamps and active deduplication."
    )
    parser.add_argument(
        "--project",
        default=config.gcp.project_id,
        help="Google Cloud project ID (default: from campaign.yaml/env)",
    )
    parser.add_argument(
        "--rule",
        choices=["R1", "R2", "R3"],
        default=None,
        help="Run a specific rule only (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print detected alerts to stdout without writing to BigQuery",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="Disable deduplication and return all detected alerts even if already active",
    )
    parser.add_argument(
        "--cooldown-minutes",
        "--cooldown",
        dest="cooldown_minutes",
        type=float,
        default=None,
        help="Cooldown window in minutes for resolved alerts (default: 2.0)",
    )

    args = parser.parse_args()

    alerts = run_all_alerts(
        project_id=args.project,
        selected_rule=args.rule,
        filter_active=not args.no_dedup,
        cooldown_minutes=args.cooldown_minutes,
    )

    if not alerts:
        logger.info("No new alerts triggered (either no issues found or all current issues are already active/in cooldown).")
        return

    print(json.dumps(alerts, indent=2, default=str))

    if not args.dry_run:
        save_alerts_to_bigquery(alerts, args.project)
        logger.info(f"Alert detection run complete. Processed {len(alerts)} alerts.")
    else:
        logger.info(f"[DRY-RUN] Detected {len(alerts)} new alert(s) (not saved to BigQuery).")


if __name__ == "__main__":
    main()
