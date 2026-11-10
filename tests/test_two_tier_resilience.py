import pytest
from unittest.mock import MagicMock
from google.api_core import exceptions as g_exceptions

from core.config import get_config
from core.exceptions import DatabaseError
from core.resilience import classify_error
import core.bigquery_client as bq_client
import agents.tools.bigquery_tools as bq_tools


def test_config_loads_retry_values_from_yaml():
    config = get_config()
    assert config.resilience.max_retry_count == 2
    assert config.resilience.retry_count == 2
    assert config.resilience.backoff_min_sec == 0.5
    assert config.resilience.backoff_max_sec == 2.0
    assert config.resilience.timeout_sec == 15.0
    assert config.investigation.max_retry_count == 2


def test_classify_error_rules():
    # Permanent errors (must not retry)
    assert classify_error(g_exceptions.NotFound("Table not found")) is False
    assert classify_error(g_exceptions.BadRequest("Syntax error")) is False
    assert classify_error(g_exceptions.Forbidden("Access denied")) is False
    assert classify_error(ValueError("Invalid numeric threshold")) is False
    assert classify_error(KeyError("missing_col")) is False

    # Transient errors (eligible for Tenacity client retry)
    assert classify_error(g_exceptions.ServiceUnavailable("BigQuery 503")) is True
    assert classify_error(g_exceptions.TooManyRequests("Rate limited 429")) is True
    assert classify_error(g_exceptions.DeadlineExceeded("Deadline exceeded")) is True
    assert classify_error(g_exceptions.GatewayTimeout("Gateway timeout 504")) is True
    assert classify_error(TimeoutError("Connection timed out")) is True
    assert classify_error(ConnectionError("Reset by peer")) is True


def test_tier1_client_retries_transient_and_succeeds(monkeypatch):
    """Tier 1: Tenacity automatically retries transient error and succeeds on 2nd attempt."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    attempts = 0

    class MockJob:
        def result(self, timeout=None):
            return [{"campaign_id": "CMP131", "status": "ACTIVE"}]

    class MockClient:
        def query(self, sql, job_config=None, timeout=None):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise g_exceptions.ServiceUnavailable("Transient 503 glitch")
            return MockJob()

    monkeypatch.setattr(bq_client, "get_bigquery_client", lambda: MockClient())

    rows = bq_client.execute_query("SELECT * FROM silver.campaigns")
    assert len(rows) == 1
    assert rows[0]["campaign_id"] == "CMP131"
    assert attempts == 2
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == 0.5  # backoff_min_sec from campaign.yaml


def test_tier1_client_fails_fast_on_permanent_error(monkeypatch):
    """Tier 1: Tenacity never retries permanent errors like 404 or 400."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    class MockClient:
        def query(self, sql, job_config=None, timeout=None):
            raise g_exceptions.NotFound("Dataset offers_silver not found")

    monkeypatch.setattr(bq_client, "get_bigquery_client", lambda: MockClient())

    with pytest.raises(DatabaseError) as exc_info:
        bq_client.execute_query("SELECT * FROM silver.campaigns")

    assert exc_info.value.attempts_made == 1
    assert exc_info.value.is_transient is False
    assert len(sleep_calls) == 0  # Zero delay, failed fast


def test_tier1_client_exhausts_transient_retries(monkeypatch):
    """Tier 1: When transient error persists, Tenacity exhausts retries and raises DatabaseError."""
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    class MockClient:
        def query(self, sql, job_config=None, timeout=None):
            raise g_exceptions.ServiceUnavailable("Continuous 503 outage")

    monkeypatch.setattr(bq_client, "get_bigquery_client", lambda: MockClient())

    with pytest.raises(DatabaseError) as exc_info:
        bq_client.execute_query("SELECT * FROM silver.campaigns")

    assert exc_info.value.attempts_made == 2
    assert exc_info.value.is_transient is True
    assert exc_info.value.retryable is False
    assert len(sleep_calls) == 1  # Retried 1 time (attempts: 1 -> 2)


def test_tier2_tool_reports_exhausted_transient_to_llm(monkeypatch):
    """Tier 2: Tool formats exhausted client error with full diagnostics for LLM."""
    def failing_query(sql, parameters=None, client=None, timeout_sec=None):
        raise DatabaseError(
            "BigQuery 503 Backend Unavailable",
            retryable=False,
            attempts_made=2,
            is_transient=True,
        )

    monkeypatch.setattr(bq_client, "execute_query", failing_query)

    res = bq_tools.get_campaign_terms("CMP131")
    assert res["success"] is False
    assert res["campaign_id"] == "CMP131"
    assert res["terms"] is None
    assert res["error_type"] == "INFRASTRUCTURE_UNAVAILABLE"
    assert res["retryable"] is False
    assert res["attempts_made"] == 2
    assert res["max_attempts"] == 2
    assert res["remaining_attempts"] == 0
    assert "Database client already retried 2 time(s)" in res["suggested_action"]
    assert "Do NOT retry this tool" in res["suggested_action"]


def test_tier2_tool_reports_permanent_error_to_llm(monkeypatch):
    """Tier 2: Tool formats permanent error with full diagnostics for LLM."""
    def failing_query(sql, parameters=None, client=None, timeout_sec=None):
        raise DatabaseError(
            "Column 'foo' does not exist",
            retryable=False,
            attempts_made=1,
            is_transient=False,
        )

    monkeypatch.setattr(bq_client, "execute_query", failing_query)

    res = bq_tools.get_campaign_terms("CMP131")
    assert res["success"] is False
    assert res["error_type"] == "PERMANENT_DATA_ERROR"
    assert res["retryable"] is False
    assert res["attempts_made"] == 1
    assert res["remaining_attempts"] == 0
    assert "Permanent query, schema, or missing record error" in res["suggested_action"]
