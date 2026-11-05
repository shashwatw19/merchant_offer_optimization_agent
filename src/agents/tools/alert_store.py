from typing import Any, Dict, List
from google.cloud import bigquery
import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger


def ensure_alert_table() -> None:
    """Ensure the offers_gold.alerts table exists in BigQuery."""
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
            investigation_summary STRING
        )
    """
    try:
        bq_client.execute_query(sql)
        logger.info(f"Verified existence of alerts table `{project}.{gold}.alerts`")
    except Exception as exc:
        logger.warning(f"Could not verify/create alerts table: {exc}")


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
    """Update an alert's status to 'PROCESSING', 'RESOLVED', or 'ERROR'."""
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        UPDATE `{project}.{gold}.alerts`
        SET status = @status,
            resolved_at = CURRENT_TIMESTAMP(),
            investigation_summary = @summary
        WHERE alert_id = @alert_id
    """
    params = [
        bigquery.ScalarQueryParameter("status", "STRING", status),
        bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id),
        bigquery.ScalarQueryParameter("summary", "STRING", summary or ""),
    ]
    try:
        bq_client.execute_query(sql, parameters=params)
        logger.info(f"Updated alert {alert_id} status -> {status}")
        return True
    except Exception as exc:
        logger.error(f"Failed to update alert {alert_id} status: {exc}")
        return False
