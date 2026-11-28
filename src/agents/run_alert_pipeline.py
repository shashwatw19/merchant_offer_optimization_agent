import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.agent import process_alert_async
from agents.tools.bigquery_tools import get_campaign_terms
from core.config import get_config
from core.logging import logger
from core.time_utils import now_ist_str
from services.alert_store import (
    ensure_alert_table,
    fetch_pending_alerts,
    update_alert_status,
)
from services.report_converter import convert_json_report_to_markdown
from services.run_store import ensure_agent_runs_table


async def process_alert_batch(
    alerts: List[Dict[str, Any]],
    output_dir: Optional[Path] = None,
    dry_run: bool = False,
    batch_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Process a batch of alerts concurrently or sequentially with status tracking and execution metrics."""
    results = []
    eff_batch_id = batch_id or f"BATCH_{now_ist_str()[:10].replace('-', '')}"

    for alert in alerts:
        alert_id = alert["alert_id"]
        campaign_id = alert["campaign_id"]
        rule_id = alert.get("rule_id") or alert.get("rule") or "DEFAULT"
        logger.info(f"Starting investigation for alert {alert_id} (Campaign: {campaign_id}, Rule: {rule_id}, Batch: {eff_batch_id})")

        if not dry_run:
            update_alert_status(alert_id, "PROCESSING")

        result = await process_alert_async(alert, batch_id=eff_batch_id)
        results.append(result)

        if result["success"]:
            report = result["report"]
            if not report.get("campaign_terms") and campaign_id:
                try:
                    terms_res = get_campaign_terms(campaign_id)
                    if terms_res.get("success") and terms_res.get("terms"):
                        report["campaign_terms"] = terms_res.get("terms")
                except Exception:
                    pass
            exec_id = result.get("execution_id") or report.get("execution_id") or f"exec_{alert_id}"
            summary = report.get("summary") or "Investigation completed successfully."
            playbook_used = result.get("playbook") or rule_id
            logger.info(f"Alert {alert_id} investigation completed successfully (Exec: {exec_id}, Playbook: {playbook_used}).")

            # If an output_dir is explicitly specified, save local copy; otherwise rely solely on BigQuery
            if output_dir:
                try:
                    report_file = output_dir / f"report_{alert_id}.json"
                    with open(report_file, "w", encoding="utf-8") as f:
                        json.dump(report, f, indent=2, default=str)
                    logger.info(f"Saved investigation report JSON locally to {report_file}")
                except Exception as file_err:
                    logger.warning(f"Could not save local JSON report: {file_err}")

                try:
                    md_file = output_dir / f"report_{alert_id}.md"
                    md_res = convert_json_report_to_markdown(
                        report_data=report,
                        execution_id=exec_id,
                        output_path=str(md_file),
                        save_to_gcs=False,
                    )
                    result["markdown_content"] = md_res.get("markdown_content")
                except Exception as md_err:
                    logger.warning(f"Could not render Markdown report: {md_err}")

            result["gcs_json_uri"] = None
            result["gcs_markdown_uri"] = None

            if not dry_run:
                update_alert_status(alert_id, "RESOLVED", summary=summary)
        else:
            err = result.get("error", "Unknown error")
            logger.error(f"Alert {alert_id} failed: {err}")
            if not dry_run:
                update_alert_status(alert_id, "ERROR", summary=f"Error: {err}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch pipeline to investigate pending campaign alerts."
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of alerts to process.")
    parser.add_argument("--alert-id", type=str, default=None, help="Specific alert ID to investigate.")
    parser.add_argument("--batch-id", type=str, default=None, help="Optional batch identifier for execution metrics.")
    parser.add_argument("--output-dir", type=str, default=None, help="Optional directory to save report JSON files.")
    parser.add_argument("--dry-run", action="store_true", help="Run without updating BigQuery alert statuses.")

    args = parser.parse_args()
    config = get_config()

    output_dir = Path(args.output_dir) if args.output_dir else None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

    if not args.dry_run:
        ensure_alert_table()
        ensure_agent_runs_table()

    if args.alert_id:
        pending_alerts = [
            {
                "alert_id": args.alert_id,
                "campaign_id": "CMP_SPECIFIED",
                "rule_id": "R1",
                "metric_name": "manual_trigger",
                "metric_value": 0.0,
                "threshold_value": 5.0,
                "status": "OPEN",
                "created_at": now_ist_str(),
            }
        ]
    else:
        pending_alerts = fetch_pending_alerts(limit=args.limit)

    if not pending_alerts:
        logger.info(f"No OPEN alerts found in `{config.gcp.project_id}.{config.gcp.gold_dataset}.alerts`")
        return

    logger.info(f"Found {len(pending_alerts)} pending alert(s) to process.")
    results = asyncio.run(
        process_alert_batch(
            pending_alerts,
            output_dir=output_dir,
            dry_run=args.dry_run,
            batch_id=args.batch_id,
        )
    )

    successes = sum(1 for r in results if r.get("success"))
    logger.info(f"Pipeline finished: {successes}/{len(results)} alerts successfully investigated.")


if __name__ == "__main__":
    main()
