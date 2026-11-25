"""Rate-limited, validated, instrumented BigQuery execution for chat queries."""

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from google.cloud import bigquery
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from analytics.catalog import BUILTIN_TABLE_CATALOG
from analytics.models import QueryExecutionMetric, SQLValidationResult
from analytics.validator import SQLSafetyValidator
from core.bigquery_client import get_bigquery_client, make_serializable
from core.config import get_config
from core.resilience import TRANSIENT_EXCEPTIONS

logger = logging.getLogger("analytics.client")

PII_CARD_PATTERN = re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b")
PII_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def sanitize_pii(text: str) -> str:
    """Mask common payment-card and email formats before writing to logs."""
    if not text:
        return text
    return PII_EMAIL_PATTERN.sub(
        "[MASKED_EMAIL]",
        PII_CARD_PATTERN.sub("[MASKED_CARD]", text),
    )


class SimpleRateLimiter:
    """Thread-safe in-memory sliding-window query limiter."""

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.request_timestamps: List[float] = []
        self._lock = threading.Lock()

    def check_and_record(self) -> Tuple[bool, Optional[str]]:
        now = time.monotonic()
        with self._lock:
            self.request_timestamps = [
                timestamp
                for timestamp in self.request_timestamps
                if now - timestamp < self.window_seconds
            ]
            if len(self.request_timestamps) >= self.max_requests:
                retry_after = max(
                    1,
                    int(self.window_seconds - (now - self.request_timestamps[0])),
                )
                return False, (
                    f"Rate limit reached ({self.max_requests} queries per "
                    f"{self.window_seconds} seconds). Please wait {retry_after}s."
                )
            self.request_timestamps.append(now)
        return True, None


class AnalyticsBigQueryClient:
    """Dedicated query layer with SQL validation, cost ceiling, and audit metrics."""

    def __init__(
        self,
        base_client: Optional[Any] = None,
        validator: Optional[SQLSafetyValidator] = None,
        max_rows_limit: int = 200,
        default_limit: int = 100,
        rate_limit_per_min: int = 30,
        max_bytes_billed: Optional[int] = None,
    ):
        self._base_client = base_client or get_bigquery_client()
        config = get_config()
        project_id = getattr(getattr(config, "gcp", None), "project_id", None)
        self._bq_client = self._base_client
        client_project = getattr(self._bq_client, "project", None)
        if isinstance(project_id, str) and project_id:
            self.project_id = project_id
        elif isinstance(client_project, str) and client_project:
            self.project_id = client_project
        else:
            self.project_id = None
        self.validator = validator or SQLSafetyValidator(
            max_allowed_limit=max_rows_limit,
            default_limit=default_limit,
            allowed_tables=BUILTIN_TABLE_CATALOG,
            project_id=self.project_id,
        )
        self.rate_limiter = SimpleRateLimiter(max_requests=rate_limit_per_min, window_seconds=60)
        self.max_rows_limit = max_rows_limit
        self.default_limit = default_limit
        self.max_bytes_billed = max_bytes_billed or int(
            os.environ.get("ANALYTICS_MAX_BYTES_BILLED", str(500 * 1024 * 1024))
        )
        self.recent_metrics: List[QueryExecutionMetric] = []
        self._metrics_lock = threading.Lock()
        self._max_audit_logs = 100

    def execute_readonly_query(
        self,
        sql: str,
        user_question: str = "",
        request_limit: int = 100,
        timeout: int = 60,
    ) -> Tuple[List[Dict[str, Any]], SQLValidationResult, QueryExecutionMetric]:
        query_id = f"Q-{uuid4().hex[:10]}"
        timestamp = datetime.now(timezone.utc).isoformat()
        allowed, rate_message = self.rate_limiter.check_and_record()
        if not allowed:
            metric = QueryExecutionMetric(
                query_id=query_id,
                user_question=sanitize_pii(user_question),
                sql=sanitize_pii(sql),
                validation_status="RATE_LIMITED",
                tables_accessed=[],
                execution_time_ms=0.0,
                rows_returned=0,
                timestamp=timestamp,
                error=rate_message,
            )
            self._record_metric(metric)
            logger.warning("Analytics query rate limit reached: %s", rate_message)
            raise RuntimeError(rate_message)

        validation = self.validator.validate(sql, request_limit=request_limit)
        if not validation.is_valid:
            error_message = "; ".join(validation.violation_reasons)
            metric = QueryExecutionMetric(
                query_id=query_id,
                user_question=sanitize_pii(user_question),
                sql=sanitize_pii(sql),
                validation_status="BLOCKED",
                tables_accessed=validation.tables_accessed,
                execution_time_ms=0.0,
                rows_returned=0,
                timestamp=timestamp,
                error=error_message,
            )
            self._record_metric(metric)
            logger.warning("Blocked analytics query %s: %s", query_id, error_message)
            raise PermissionError(f"Query rejected by SQL safety validator: {error_message}")

        job_config = bigquery.QueryJobConfig()
        job_config.use_legacy_sql = False
        job_config.maximum_bytes_billed = self.max_bytes_billed
        retry_count = max(1, int(getattr(getattr(get_config(), "resilience", None), "max_retry_count", 2)))
        backoff_min = float(getattr(getattr(get_config(), "resilience", None), "backoff_min_sec", 0.5))
        backoff_max = float(getattr(getattr(get_config(), "resilience", None), "backoff_max_sec", 2.0))
        start = time.perf_counter()
        try:
            retryer = Retrying(
                stop=stop_after_attempt(retry_count),
                wait=wait_exponential(multiplier=backoff_min, min=backoff_min, max=backoff_max),
                retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
                reraise=True,
            )
            query_job = None
            for attempt in retryer:
                with attempt:
                    query_job = self._bq_client.query(
                        validation.sanitized_sql,
                        job_config=job_config,
                        timeout=timeout,
                    )
                    result = query_job.result(timeout=timeout)
                    rows = [
                        make_serializable(dict(row.items()) if hasattr(row, "items") else dict(row))
                        for row in result
                    ]
            execution_ms = round((time.perf_counter() - start) * 1000, 2)
            bytes_processed = getattr(query_job, "total_bytes_processed", None)
            if not isinstance(bytes_processed, int):
                bytes_processed = None
            metric = QueryExecutionMetric(
                query_id=query_id,
                user_question=sanitize_pii(user_question),
                sql=sanitize_pii(validation.sanitized_sql),
                validation_status="EXECUTED",
                tables_accessed=validation.tables_accessed,
                execution_time_ms=execution_ms,
                rows_returned=len(rows),
                bytes_processed=bytes_processed,
                timestamp=timestamp,
            )
            self._record_metric(metric)
            logger.info(
                "Analytics query %s completed in %sms (%s rows)",
                query_id,
                execution_ms,
                len(rows),
            )
            return rows, validation, metric
        except Exception as exc:
            execution_ms = round((time.perf_counter() - start) * 1000, 2)
            safe_error = sanitize_pii(str(exc))
            metric = QueryExecutionMetric(
                query_id=query_id,
                user_question=sanitize_pii(user_question),
                sql=sanitize_pii(validation.sanitized_sql),
                validation_status="FAILED",
                tables_accessed=validation.tables_accessed,
                execution_time_ms=execution_ms,
                rows_returned=0,
                timestamp=timestamp,
                error=safe_error,
            )
            self._record_metric(metric)
            logger.error("Analytics query %s failed: %s", query_id, safe_error)
            raise RuntimeError(f"BigQuery query execution failed: {safe_error}") from exc

    def _record_metric(self, metric: QueryExecutionMetric) -> None:
        with self._metrics_lock:
            self.recent_metrics.insert(0, metric)
            del self.recent_metrics[self._max_audit_logs :]

    def get_audit_history(self, limit: int = 50) -> List[QueryExecutionMetric]:
        with self._metrics_lock:
            return list(self.recent_metrics[: max(0, limit)])


_analytics_bq_client: Optional[AnalyticsBigQueryClient] = None


def get_analytics_bq_client() -> AnalyticsBigQueryClient:
    global _analytics_bq_client
    if _analytics_bq_client is None:
        _analytics_bq_client = AnalyticsBigQueryClient()
    return _analytics_bq_client
