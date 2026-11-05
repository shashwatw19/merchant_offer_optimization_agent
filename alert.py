import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure src is on sys.path
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from domain.rules import get_rule_queries, parse_alert_row


def run_rule_alerts(rule_id: str, project_id: str) -> List[Dict[str, Any]]:
    """Execute a single alert rule query and return standardized alert payloads."""
    queries = get_rule_queries(project_id)
    if rule_id not in queries:
        logger.error(f"Unknown rule ID '{rule_id}'. Allowed: {list(queries.keys())}")
        return []

    sql = queries[rule_id]
    logger.info(f"Evaluating rule {rule_id} in BigQuery...")
    try:
        rows = bq_client.execute_query(sql)
        alerts = [parse_alert_row(row) for row in rows]
        logger.info(f"Rule {rule_id} triggered {len(alerts)} alert(s).")
        return alerts
    except Exception as exc:
        logger.error(f"Failed executing query for rule {rule_id}: {exc}")
        return []


def run_all_alerts(project_id: str, selected_rule: str = None) -> List[Dict[str, Any]]:
    """Execute all configured deterministic alert rules (R1, R2, R3)."""
    rules_to_run = [selected_rule] if selected_rule else ["R1", "R2", "R3"]
    all_alerts = []

    for rule_id in rules_to_run:
        rule_alerts = run_rule_alerts(rule_id, project_id)
        all_alerts.extend(rule_alerts)

    return all_alerts


def save_alerts_to_bigquery(alerts: List[Dict[str, Any]], project_id: str) -> None:
    """Insert triggered alerts into BigQuery offers_gold.alerts table."""
    if not alerts:
        return

    config = get_config()
    table_id = f"{project_id}.{config.gcp.gold_dataset}.alerts"
    client = bq_client.get_bigquery_client(project_id)

    errors = client.insert_rows_json(table_id, alerts)
    if errors:
        logger.error(f"BigQuery alert insertion failed: {errors}")
        raise RuntimeError(f"BigQuery insert failed: {errors}")

    logger.info(f"Successfully inserted {len(alerts)} alerts into `{table_id}`")


def main() -> None:
    config = get_config()

    parser = argparse.ArgumentParser(
        description="Deterministic alert detection engine for merchant offer optimization."
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

    args = parser.parse_args()

    alerts = run_all_alerts(args.project, selected_rule=args.rule)

    if not alerts:
        logger.info("No alerts triggered based on current Gold metrics.")
        return

    print(json.dumps(alerts, indent=2, default=str))

    if not args.dry_run:
        save_alerts_to_bigquery(alerts, args.project)
        logger.info(f"Alert detection run complete. Processed {len(alerts)} alerts.")
    else:
        logger.info(f"[DRY-RUN] Detected {len(alerts)} alerts (not saved to BigQuery).")


if __name__ == "__main__":
    main()
