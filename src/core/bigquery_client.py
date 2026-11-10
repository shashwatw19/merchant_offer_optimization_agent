import datetime
import decimal
from typing import Any, Dict, List, Optional
from google.cloud import bigquery
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config
from core.exceptions import DatabaseError
from core.logging import logger
from core.resilience import TRANSIENT_EXCEPTIONS, classify_error

_BQ_CLIENT: Optional[bigquery.Client] = None


def make_serializable(obj: Any) -> Any:
    """Recursively convert BigQuery Decimal, Date, and Datetime objects to JSON-serializable types."""
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_serializable(item) for item in obj]
    return obj


def get_bigquery_client(project_id: Optional[str] = None) -> bigquery.Client:
    """Lazy initialize and return the BigQuery client."""
    global _BQ_CLIENT
    if _BQ_CLIENT is not None:
        return _BQ_CLIENT

    config = get_config()
    target_project = project_id or config.gcp.project_id
    try:
        _BQ_CLIENT = bigquery.Client(project=target_project)
        return _BQ_CLIENT
    except Exception as exc:
        logger.error(f"Failed to initialize BigQuery client for project '{target_project}': {exc}")
        raise DatabaseError(
            f"Could not connect to BigQuery project '{target_project}': {exc}",
            retryable=False,
            attempts_made=1,
            is_transient=False,
        ) from exc


def set_bigquery_client(client: Optional[bigquery.Client]) -> None:
    """Override the BigQuery client (used primarily in tests)."""
    global _BQ_CLIENT
    _BQ_CLIENT = client


def execute_query(
    sql: str,
    parameters: Optional[List[bigquery.ScalarQueryParameter]] = None,
    client: Optional[bigquery.Client] = None,
    timeout_sec: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Execute a parameterized query against BigQuery with Tenacity retries."""
    config = get_config()
    bq_client = client or get_bigquery_client()
    job_config = bigquery.QueryJobConfig()
    if parameters:
        job_config.query_parameters = parameters

    max_retries = getattr(config.resilience, "max_retry_count", 2)
    backoff_min = getattr(config.resilience, "backoff_min_sec", 0.5)
    backoff_max = getattr(config.resilience, "backoff_max_sec", 2.0)
    effective_timeout = timeout_sec or getattr(config.resilience, "timeout_sec", 15.0)

    retryer = Retrying(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=backoff_min, min=backoff_min, max=backoff_max),
        retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
        reraise=True,
    )

    try:
        for attempt in retryer:
            with attempt:
                job = bq_client.query(sql, job_config=job_config, timeout=effective_timeout)
                result_rows = list(job.result(timeout=effective_timeout))
                return [make_serializable(dict(row.items())) for row in result_rows]
    except Exception as exc:
        attempts = retryer.statistics.get("attempt_number", 1) if hasattr(retryer, "statistics") else 1
        is_transient = classify_error(exc)
        logger.error(f"BigQuery query error after {attempts} attempt(s): {exc}", extra={"query": sql[:200]})
        raise DatabaseError(
            f"BigQuery query execution failed: {exc}",
            retryable=False,
            query=sql,
            attempts_made=attempts,
            is_transient=is_transient,
        ) from exc
