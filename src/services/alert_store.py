"""Alert storage and persistence service."""
from typing import Any, Dict, List, Set
from google.cloud import bigquery
import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from core.time_utils import now_ist_str


def _get_alerts_columns(project: str, gold: str) -> Set[str]:
    """Retrieve existing column names from the alerts table."""
    try:
        client = bq_client.get_bigquery_client(project)
        table = client.get_table(f"{project}.{gold}.alerts")
        return {field.name.lower() for field in table.schema}
    except Exception as exc:
        logger.debug(f"Could not inspect alerts table schema: {exc}")
        return set()


def ensure_alert_table() -> None:
    """Ensure the offers_gold.alerts table exists in BigQuery with all required columns."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        CREATE TABLE IF NOT EXISTS `{project}.{gold}.alerts` (
            alert_id STRING NOT NULL,
            campaign_id STRING NOT NULL,
            merchant_id STRING,
            rule_id STRING NOT NULL,
            metric_name STRING,
            metric_value NUMERIC,
            threshold_value NUMERIC,
            status STRING NOT NULL,
            created_at STRING,
            resolved_at STRING,
            summary STRING,
            investigation_summary STRING
        )
    """
    try:
        bq_client.execute_query(sql)
        logger.info(f"Verified existence of alerts table `{project}.{gold}.alerts`")
    except Exception as exc:
        logger.warning(f"Could not verify/create alerts table: {exc}")

    # Ensure summary column exists in case the table was created earlier without it
    try:
        alter_sql = f"ALTER TABLE `{project}.{gold}.alerts` ADD COLUMN IF NOT EXISTS summary STRING"
        bq_client.execute_query(alter_sql)
    except Exception:
        pass


def fetch_pending_alerts(limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch unhandled alerts with status = 'OPEN' from BigQuery."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        SELECT
            alert_id,
            campaign_id,
            merchant_id,
            rule_id,
            metric_name,
            metric_value,
            threshold_value,
            status,
            created_at
        FROM `{project}.{gold}.alerts`
        WHERE status = 'OPEN'
        ORDER BY created_at ASC
        LIMIT @limit
    """
    params = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    try:
        return bq_client.execute_query(sql, parameters=params)
    except Exception as exc:
        logger.error(f"Failed to fetch pending alerts: {exc}")
        return []


def update_alert_status(
    alert_id: str,
    status: str,
    summary: str = None,
) -> bool:
    """Update an alert's status and summary in BigQuery."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    now_ist = now_ist_str()
    cols = _get_alerts_columns(project, gold)
    summary_text = summary or ""

    set_clauses = ["status = @status"]
    params = [
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id),
    ]

    if not cols or "resolved_at" in cols:
        set_clauses.append("resolved_at = @resolved_at")
        params.append(bigquery.ScalarQueryParameter("resolved_at", "STRING", now_ist))

    # Add summary column assignments
    if cols:
        has_summary_col = False
        if "summary" in cols:
            set_clauses.append("summary = @summary")
            has_summary_col = True
        if "investigation_summary" in cols:
            set_clauses.append("investigation_summary = @summary")
            has_summary_col = True
        if not has_summary_col:
            set_clauses.append("summary = @summary")
        params.append(bigquery.ScalarQueryParameter("summary", "STRING", summary_text))
    else:
        # Schema couldn't be pre-inspected; default to summary
        set_clauses.append("summary = @summary")
        params.append(bigquery.ScalarQueryParameter("summary", "STRING", summary_text))

    sql = f"""
    UPDATE `{project}.{gold}.alerts`
    SET {", ".join(set_clauses)}
    WHERE alert_id = @alert_id
"""
    try:
        bq_client.execute_query(sql, parameters=params)
        logger.info(f"Updated alert {alert_id} status -> {status} and recorded summary in BigQuery")
        return True
    except Exception as exc:
        err_str = str(exc).lower()
        if "unrecognized name: summary" in err_str:
            # Fallback for tables containing only investigation_summary
            fallback_sql = f"""
                UPDATE `{project}.{gold}.alerts`
                SET status = @status,
                    resolved_at = @resolved_at,
                    investigation_summary = @summary
                WHERE alert_id = @alert_id
            """
            try:
                fallback_params = [
                    bigquery.ScalarQueryParameter("status", "STRING", status),
                    bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id),
                    bigquery.ScalarQueryParameter("summary", "STRING", summary_text),
                    bigquery.ScalarQueryParameter("resolved_at", "STRING", now_ist),
                ]
                bq_client.execute_query(fallback_sql, parameters=fallback_params)
                logger.info(f"Updated alert {alert_id} status -> {status} (using investigation_summary)")
                return True
            except Exception as f_exc:
                logger.error(f"Fallback update for alert {alert_id} failed: {f_exc}")
        elif "streaming buffer" in err_str:
            logger.warning(
                f"Alert {alert_id} is temporarily in BigQuery's streaming buffer and cannot be updated yet. "
                f"Status update ({status}) will be reflected once BigQuery flushes the buffer to persistent storage."
            )
        else:
            logger.error(f"Failed to update alert {alert_id} status and summary: {exc}")
        return False
