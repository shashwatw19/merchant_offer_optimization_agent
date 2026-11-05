import datetime
import decimal
from typing import Any, Dict, List, Optional
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import get_config
from core.exceptions import DatabaseError
from core.logging import logger

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
        ) from exc


def set_bigquery_client(client: Optional[bigquery.Client]) -> None:
    """Override the BigQuery client (used primarily in tests)."""
    global _BQ_CLIENT
    _BQ_CLIENT = client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((GoogleAPICallError,)),
    reraise=True,
)
def execute_query(
    sql: str,
    parameters: Optional[List[bigquery.ScalarQueryParameter]] = None,
    client: Optional[bigquery.Client] = None,
    timeout_sec: float = 30.0,
) -> List[Dict[str, Any]]:
    """Execute a parameterized query against BigQuery with automatic retry and serialization."""
    bq_client = client or get_bigquery_client()
    job_config = bigquery.QueryJobConfig()
    if parameters:
        job_config.query_parameters = parameters

    try:
        job = bq_client.query(sql, job_config=job_config, timeout=timeout_sec)
        result_rows = list(job.result(timeout=timeout_sec))
        return [make_serializable(dict(row.items())) for row in result_rows]
    except Exception as exc:
        logger.error(f"BigQuery query error: {exc}", extra={"query": sql[:200]})
        raise DatabaseError(
            f"BigQuery query execution failed: {exc}",
            retryable=isinstance(exc, GoogleAPICallError),
            query=sql,
        ) from exc
