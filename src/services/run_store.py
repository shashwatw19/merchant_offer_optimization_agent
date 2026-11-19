import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from google.cloud import bigquery
import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from core.time_utils import now_ist_str


def _get_agent_runs_columns(project: str, gold: str) -> Set[str]:
    """Retrieve existing column names from the agent_runs table schema."""
    try:
        client = bq_client.get_bigquery_client(project)
        table = client.get_table(f"{project}.{gold}.agent_runs")
        return {field.name.lower() for field in table.schema}
    except Exception as exc:
        logger.debug(f"Could not inspect agent_runs table schema: {exc}")
        return set()


def ensure_agent_runs_table() -> None:
    """Ensure the card_gold.agent_runs table exists in BigQuery for execution telemetry."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        CREATE TABLE IF NOT EXISTS `{project}.{gold}.agent_runs` (
            execution_id STRING NOT NULL,
            alert_id STRING NOT NULL,
            campaign_id STRING NOT NULL,
            merchant_id STRING,
            rule_id STRING,
            run_number INT64,
            status STRING NOT NULL,
            started_at STRING,
            ended_at STRING,
            duration_ms FLOAT64,
            agent_name STRING,
            model_name STRING,
            prompt_tokens INT64,
            tool_use_tokens INT64,
            input_tokens INT64,
            candidates_tokens INT64,
            thoughts_tokens INT64,
            output_tokens INT64,
            total_tokens INT64,
            cached_tokens INT64,
            tool_call_count INT64,
            tool_latency_ms FLOAT64,
            tool_calls STRING,
            gcs_json_uri STRING,
            gcs_markdown_uri STRING,
            error_type STRING,
            error_message STRING,
            created_at STRING
        )
    """
    try:
        bq_client.execute_query(sql)
        logger.info(f"Verified existence of agent_runs table `{project}.{gold}.agent_runs`")
    except Exception as exc:
        logger.warning(f"Could not verify/create agent_runs table: {exc}")

    # Ensure newly added columns exist in case the table was created under an earlier schema
    for col, col_type in [
        ("run_number", "INT64"),
        ("gcs_json_uri", "STRING"),
        ("gcs_markdown_uri", "STRING"),
        ("cached_tokens", "INT64"),
        ("tool_use_tokens", "INT64"),
    ]:
        try:
            alter_sql = f"ALTER TABLE `{project}.{gold}.agent_runs` ADD COLUMN IF NOT EXISTS {col} {col_type}"
            bq_client.execute_query(alter_sql)
        except Exception:
            pass


def get_next_run_number(alert_id: str) -> int:
    """Determine the next run sequence number (1, 2, 3...) for an alert by querying prior runs."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset
    sql = f"""
        SELECT COUNT(*) as total_runs
        FROM `{project}.{gold}.agent_runs`
        WHERE alert_id = @alert_id
    """
    try:
        rows = bq_client.execute_query(
            sql,
            parameters=[bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id)],
            timeout_sec=5.0,
        )
        if rows and "total_runs" in rows[0]:
            return int(rows[0]["total_runs"]) + 1
    except Exception as exc:
        logger.debug(f"Could not query prior runs from BigQuery for {alert_id}: {exc}")

    # Fallback to local trace/output files if BigQuery is unavailable or table is empty
    try:
        for search_dir in [Path("output"), Path("data/traces")]:
            if search_dir.is_dir():
                matches = list(search_dir.glob(f"*{alert_id}*.json"))
                if matches:
                    return len(set(f.stem for f in matches)) + 1
    except Exception:
        pass

    return 1


def generate_execution_id(alert_id: str, run_number: Optional[int] = None) -> str:
    """Generate a clean, unambiguous execution ID incorporating alert_id, timestamp, and run sequence number."""
    ts = int(time.time())
    if run_number is None:
        run_number = get_next_run_number(alert_id)
    return f"exec_{alert_id}_{ts}_run{run_number}"


def record_agent_run(
    execution_id: str,
    alert_id: str,
    campaign_id: str,
    status: str,
    metrics: Dict[str, Any],
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    merchant_id: Optional[str] = None,
    rule_id: Optional[str] = None,
    run_number: Optional[int] = None,
    gcs_json_uri: Optional[str] = None,
    gcs_markdown_uri: Optional[str] = None,
    error: Optional[str] = None,
    error_type: Optional[str] = None,
    agent_name: Optional[str] = None,
    model_name: Optional[str] = None,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
) -> bool:
    """Persist an independent agent run record to BigQuery card_gold.agent_runs.

    Non-blocking: Logs failure if BigQuery write encounters an issue without interrupting the workflow.
    """
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset
    table_id = f"{project}.{gold}.agent_runs"

    current_time_ist = now_ist_str()
    tool_calls_json = json.dumps(tool_calls or [], default=str)

    # Determine run number if not provided
    resolved_run_num = run_number
    if resolved_run_num is None:
        match = re.search(r"_run(\d+)", execution_id) or re.search(r"_(\d+)$", execution_id)
        if match:
            resolved_run_num = int(match.group(1))
        else:
            resolved_run_num = 1

    # Extract tool_use_tokens with fallback estimation if reported as 0
    resolved_tool_tokens = int(
        metrics.get("tool_use_tokens", 0)
        or metrics.get("tool_used_token", 0)
        or metrics.get("tool_used_tokens", 0)
        or 0
    )
    if not resolved_tool_tokens and tool_calls:
        payload_chars = sum(
            len(str(t.get("args", ""))) + len(str(t.get("response", "")))
            for t in tool_calls
        )
        resolved_tool_tokens = max(1, payload_chars // 4)

    # Extract cached_tokens
    resolved_cached_tokens = int(
        metrics.get("cached_tokens", 0)
        or metrics.get("cached_token", 0)
        or metrics.get("cached_content_token_count", 0)
        or 0
    )

    run_record: Dict[str, Any] = {
        "execution_id": execution_id,
        "alert_id": alert_id,
        "campaign_id": campaign_id,
        "merchant_id": merchant_id or "",
        "rule_id": rule_id or "",
        "run_number": resolved_run_num,
        "status": status,
        "started_at": started_at or current_time_ist,
        "ended_at": ended_at or current_time_ist,
        "duration_ms": float(metrics.get("duration_ms", 0.0) or 0.0),
        "agent_name": agent_name or getattr(getattr(config, "agent", None), "name", "merchant_offer_optimization_agent"),
        "model_name": model_name or metrics.get("model") or getattr(getattr(config, "agent", None), "model", "gemini-3.5-flash"),
        "prompt_tokens": int(metrics.get("prompt_tokens", 0) or 0),
        "tool_use_tokens": resolved_tool_tokens,
        "input_tokens": int(metrics.get("input_tokens", 0) or (int(metrics.get("prompt_tokens", 0) or 0) + resolved_tool_tokens)),
        "candidates_tokens": int(metrics.get("candidates_tokens", 0) or 0),
        "thoughts_tokens": int(metrics.get("thoughts_tokens", 0) or 0),
        "output_tokens": int(metrics.get("output_tokens", 0) or 0),
        "total_tokens": int(metrics.get("total_tokens", 0) or 0),
        "cached_tokens": resolved_cached_tokens,
        "tool_call_count": int(metrics.get("tool_call_count", len(tool_calls or []))),
        "tool_latency_ms": float(metrics.get("tool_latency_ms", 0.0) or 0.0),
        "tool_calls": tool_calls_json,
        "gcs_json_uri": gcs_json_uri or "",
        "gcs_markdown_uri": gcs_markdown_uri or "",
        "error_type": error_type or ("ERROR" if error else "NONE"),
        "error_message": str(error or ""),
        "created_at": current_time_ist,
    }

    # Adapt dynamically to any schema variations in BigQuery
    existing_cols = _get_agent_runs_columns(project, gold)
    if existing_cols:
        if "tool_used_token" in existing_cols and "tool_used_token" not in run_record:
            run_record["tool_used_token"] = resolved_tool_tokens
        if "tool_used_tokens" in existing_cols and "tool_used_tokens" not in run_record:
            run_record["tool_used_tokens"] = resolved_tool_tokens
        if "cached_token" in existing_cols and "cached_token" not in run_record:
            run_record["cached_token"] = resolved_cached_tokens
        # Only retain columns actually present in the table schema if schema was inspected
        run_record = {k: v for k, v in run_record.items() if k.lower() in existing_cols}

    try:
        client = bq_client.get_bigquery_client(project)
        # Use batch load to avoid streaming buffer locks
        job = client.load_table_from_json([run_record], table_id)
        job.result(timeout=15.0)
        logger.info(f"Recorded agent run telemetry to `{table_id}` for execution {execution_id}")
        return True
    except Exception as exc:
        logger.warning(f"Batch load for agent_runs failed ({exc}), attempting streaming insert...")
        try:
            client = bq_client.get_bigquery_client(project)
            errors = client.insert_rows_json(table_id, [run_record])
            if errors:
                logger.error(f"Streaming insert to agent_runs failed: {errors}")
                return False
            logger.info(f"Streamed agent run telemetry to `{table_id}` for execution {execution_id}")
            return True
        except Exception as inner_exc:
            logger.error(f"Could not record agent run telemetry for {execution_id}: {inner_exc}")
            return False


def update_agent_run_gcs_uris(
    execution_id: str,
    gcs_json_uri: Optional[str] = None,
    gcs_markdown_uri: Optional[str] = None,
) -> bool:
    """Update GCS artifact URIs for an existing agent execution record in card_gold.agent_runs."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset
    table_id = f"{project}.{gold}.agent_runs"

    sql = f"""
        UPDATE `{table_id}`
        SET gcs_json_uri = @gcs_json_uri,
            gcs_markdown_uri = @gcs_markdown_uri
        WHERE execution_id = @execution_id
    """
    params = [
        bigquery.ScalarQueryParameter("execution_id", "STRING", execution_id),
        bigquery.ScalarQueryParameter("gcs_json_uri", "STRING", gcs_json_uri or ""),
        bigquery.ScalarQueryParameter("gcs_markdown_uri", "STRING", gcs_markdown_uri or ""),
    ]
    try:
        bq_client.execute_query(sql, parameters=params)
        logger.info(f"Updated GCS URIs in agent_runs for execution {execution_id}")
        return True
    except Exception as exc:
        logger.warning(f"Could not update GCS URIs for {execution_id} in agent_runs: {exc}")
        return False


def fetch_agent_runs(
    limit: int = 50,
    alert_id: Optional[str] = None,
    campaign_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query recent agent execution records from BigQuery card_gold.agent_runs."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    where_clauses = []
    params = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]

    if alert_id:
        where_clauses.append("alert_id = @alert_id")
        params.append(bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id))
    if campaign_id:
        where_clauses.append("campaign_id = @campaign_id")
        params.append(bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id))

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    sql = f"""
        SELECT
            execution_id,
            alert_id,
            campaign_id,
            merchant_id,
            rule_id,
            status,
            started_at,
            ended_at,
            duration_ms,
            agent_name,
            model_name,
            prompt_tokens,
            tool_use_tokens,
            input_tokens,
            output_tokens,
            total_tokens,
            cached_tokens,
            tool_call_count,
            tool_latency_ms,
            gcs_json_uri,
            gcs_markdown_uri,
            error_type,
            error_message,
            created_at
        FROM `{project}.{gold}.agent_runs`
        {where_sql}
        ORDER BY created_at DESC
        LIMIT @limit
    """
    try:
        return bq_client.execute_query(sql, parameters=params)
    except Exception as exc:
        logger.warning(f"Could not fetch agent runs from `{project}.{gold}.agent_runs`: {exc}")
        return []
