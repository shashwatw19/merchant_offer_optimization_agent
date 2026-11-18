"""
src/agents/runner.py
Audit persistence and execution metrics runner for Merchant Offer Optimization Agent.
Persists step-by-step traces, model token usage, and proposal verdicts into BigQuery table offers_gold.agent_runs.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import uuid4
from google.cloud import bigquery

from core.bigquery_client import get_bigquery_client, execute_query
from core.config import get_config
from core.logging import logger
from agents.metrics import InvestigationMetrics

IST = timezone(timedelta(hours=5, minutes=30))
_AGENT_RUNS_TABLE_INITIALIZED = False


def _get_agent_runs_table() -> str:
    config = get_config()
    target_project = getattr(getattr(config, "gcp", None), "project_id", "prj-imp-act-campaign")
    gold_dataset = getattr(getattr(config, "gcp", None), "gold_dataset", "offers_gold")
    default_table = f"{target_project}.{gold_dataset}.agent_runs"
    table_id = os.environ.get("AGENT_RUNS_TABLE", default_table)
    if "." not in table_id:
        table_id = f"{gold_dataset}.{table_id}"
    return table_id


def ensure_agent_runs_table() -> None:
    """Creates the offers_gold.agent_runs BigQuery audit table if it does not already exist."""
    global _AGENT_RUNS_TABLE_INITIALIZED
    if _AGENT_RUNS_TABLE_INITIALIZED:
        return

    table_id = _get_agent_runs_table()
    ddl = f"""
    CREATE TABLE IF NOT EXISTS `{table_id}` (
      alert_id STRING NOT NULL OPTIONS(description = 'The investigated alert tracking ID'),
      campaign_id STRING OPTIONS(description = 'Associated campaign identifier'),
      run_number INT64 NOT NULL OPTIONS(description = 'Iteration index of the investigation'),
      run_time TIMESTAMP NOT NULL OPTIONS(description = 'Execution timestamp in IST (Asia/Kolkata)'),
      recommendation STRING NOT NULL OPTIONS(description = 'Proposal type: KEEP, TEST, MONITOR, INVESTIGATE, REJECT, or FAILED'),
      confidence STRING NOT NULL OPTIONS(description = 'COMPLETE, INCONCLUSIVE, or FAILED'),
      tool_calls JSON OPTIONS(description = 'Step-by-step trace of tool names, arguments, and returned results'),
      output_json JSON NOT NULL OPTIONS(description = 'Validated report JSON, or JSON null for failed runs'),
      batch_id STRING OPTIONS(description = 'Unified batch identifier'),
      run_id STRING,
      run_status STRING,
      duration_ms FLOAT64,
      execution_metrics JSON
    )
    PARTITION BY DATE(run_time)
    CLUSTER BY alert_id;
    """

    migration = f"""
    ALTER TABLE `{table_id}`
      ADD COLUMN IF NOT EXISTS campaign_id STRING,
      ADD COLUMN IF NOT EXISTS batch_id STRING,
      ADD COLUMN IF NOT EXISTS run_id STRING,
      ADD COLUMN IF NOT EXISTS run_status STRING,
      ADD COLUMN IF NOT EXISTS duration_ms FLOAT64,
      ADD COLUMN IF NOT EXISTS execution_metrics JSON
    """

    try:
        client = get_bigquery_client()
        client.query(ddl).result()
        try:
            client.query(migration).result()
        except Exception:
            pass
        _AGENT_RUNS_TABLE_INITIALIZED = True
        logger.info(f"Verified BigQuery audit table: {table_id}")
    except Exception as exc:
        logger.warning(f"Could not verify or create agent_runs table `{table_id}`: {exc}")


def _next_run_number(alert_id: str, fallback_run_number: int = 1) -> int:
    """Returns the next sequential run number for an alert, persisting history across batches."""
    table_id = _get_agent_runs_table()
    query = f"""
    SELECT COALESCE(MAX(run_number), 0) + 1 AS next_run_number
    FROM `{table_id}`
    WHERE alert_id = @alert_id
    """
    try:
        rows = execute_query(
            query,
            parameters=[bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id)],
        )
        if rows:
            return int(rows[0].get("next_run_number") or fallback_run_number)
    except Exception as exc:
        logger.debug(f"Could not resolve next run number for {alert_id} ({exc}); using fallback {fallback_run_number}")
    return int(fallback_run_number or 1)


def persist_agent_run(
    alert_id: str,
    run_number: Optional[int] = None,
    report: Optional[Dict[str, Any]] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    batch_id: Optional[str] = None,
    execution_metrics: Optional[InvestigationMetrics] = None,
    campaign_id: Optional[str] = None,
) -> None:
    """Appends an agent investigation run and execution metrics into offers_gold.agent_runs."""
    table_id = _get_agent_runs_table()
    ensure_agent_runs_table()

    resolved_run_number = _next_run_number(alert_id, fallback_run_number=run_number or 1)
    now_ist = datetime.now(IST)

    # Derive recommendation from proposal type or report status
    recommendation = "FAILED"
    confidence = "FAILED"
    cid = campaign_id
    if report and isinstance(report, dict):
        cid = cid or report.get("campaign_id")
        proposal = report.get("proposal")
        if isinstance(proposal, dict) and proposal.get("type"):
            recommendation = str(proposal.get("type")).upper()
        else:
            recommendation = str(report.get("status") or "COMPLETE").upper()
        confidence = str(report.get("status") or "COMPLETE").upper()

    run_id = execution_metrics.run_id if execution_metrics else str(uuid4())
    run_status = execution_metrics.status if execution_metrics else ("completed" if report else "failed")
    duration_ms = execution_metrics.duration_ms if execution_metrics else None
    metrics_dict = execution_metrics.to_dict() if execution_metrics else None

    query = f"""
    INSERT INTO `{table_id}` (
      alert_id,
      campaign_id,
      run_number,
      run_time,
      recommendation,
      confidence,
      tool_calls,
      output_json,
      batch_id,
      run_id,
      run_status,
      duration_ms,
      execution_metrics
    ) VALUES (
      @alert_id,
      @campaign_id,
      @run_number,
      @run_time,
      @recommendation,
      @confidence,
      PARSE_JSON(@tool_calls),
      PARSE_JSON(@output_json),
      @batch_id,
      @run_id,
      @run_status,
      @duration_ms,
      PARSE_JSON(@execution_metrics)
    )
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id),
            bigquery.ScalarQueryParameter("campaign_id", "STRING", cid or ""),
            bigquery.ScalarQueryParameter("run_number", "INT64", resolved_run_number),
            bigquery.ScalarQueryParameter("run_time", "TIMESTAMP", now_ist),
            bigquery.ScalarQueryParameter("recommendation", "STRING", recommendation),
            bigquery.ScalarQueryParameter("confidence", "STRING", confidence),
            bigquery.ScalarQueryParameter("tool_calls", "STRING", json.dumps(tool_calls or [])),
            bigquery.ScalarQueryParameter("output_json", "STRING", json.dumps(report) if report else "null"),
            bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id or "OFFER_AGENT_RUN"),
            bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
            bigquery.ScalarQueryParameter("run_status", "STRING", run_status),
            bigquery.ScalarQueryParameter("duration_ms", "FLOAT64", duration_ms),
            bigquery.ScalarQueryParameter(
                "execution_metrics", "STRING",
                json.dumps(metrics_dict) if metrics_dict else "null",
            ),
        ]
    )

    try:
        client = get_bigquery_client()
        client.query(query, job_config=job_config).result()
        logger.info(
            f"Persisted investigation run to {table_id}: alert_id={alert_id}, "
            f"run_number={resolved_run_number}, status={run_status}, run_id={run_id}"
        )
    except Exception as exc:
        logger.warning(f"Could not persist investigation run to `{table_id}`: {exc}")


def fetch_all_alerts() -> List[str]:
    """Fetches list of all alert_ids from offers_gold.alerts."""
    config = get_config()
    table_id = getattr(getattr(config, "gcp", None), "alerts_table", "offers_gold.alerts")
    query = f"SELECT alert_id FROM `{table_id}` ORDER BY alert_id ASC"
    try:
        rows = execute_query(query)
        return [r["alert_id"] for r in rows if r.get("alert_id")]
    except Exception as exc:
        logger.error(f"Failed to fetch alerts from {table_id}: {exc}")
        return []
