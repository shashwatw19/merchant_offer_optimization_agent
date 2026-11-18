"""Tests for InvestigationMetrics and BigQuery agent_runs persistence."""

import json
from unittest.mock import MagicMock, patch
import pytest

from agents.metrics import (
    InvestigationMetrics,
    active_metrics,
    before_model,
    after_model,
    before_tool,
    after_tool,
    tool_response_failed,
)
from agents.runner import ensure_agent_runs_table, persist_agent_run, _next_run_number


def test_investigation_metrics_lifecycle():
    metrics = InvestigationMetrics()
    metrics.model_name = "gemini-3.5-flash"
    metrics.attempt = 1

    token = active_metrics.set(metrics)
    try:
        # 1. Simulate tool request & start
        call_id = "call_abc123"
        metrics.request_tool(call_id, "get_campaign_terms", {"campaign_id": "CMP101"}, step=1)
        metrics.start_tool(call_id, "get_campaign_terms", {"campaign_id": "CMP101"})

        assert len(metrics.tool_calls) == 1
        assert metrics.tool_calls[0]["status"] == "running"

        # 2. Simulate tool response & end
        metrics.tool_response(call_id, {"success": True, "terms": {"min_spend": 1000}})
        metrics.end_tool(call_id, result={"success": True}, duration_ms=150.5)

        assert metrics.tool_calls[0]["status"] == "success"
        assert metrics.tool_calls[0]["duration_ms"] == 150.5

        # 3. Simulate model call
        mock_response = MagicMock()
        mock_response.partial = False
        mock_response.model_version = "gemini-3.5-flash"
        mock_response.error_code = None
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.model_dump.return_value = {
            "prompt_token_count": 500,
            "candidates_token_count": 120,
            "total_token_count": 620,
            "cached_content_token_count": 0,
            "tool_use_prompt_token_count": 40,
            "thoughts_token_count": 30,
        }

        metrics.start_model()
        assert len(metrics.model_calls) == 1
        assert metrics.model_calls[0]["status"] == "running"

        metrics.end_model(response=mock_response)
        assert metrics.model_calls[0]["status"] == "success"
        assert metrics.model_calls[0]["usage"]["total_token_count"] == 620

        # 4. Finish metrics
        metrics.finish("completed")
        summary = metrics.to_dict()

        assert summary["status"] == "completed"
        assert summary["model_call_count"] == 1
        assert summary["tool_call_count"] == 1
        assert summary["token_totals"]["total_tokens"] == 620
        assert summary["token_totals"]["input_tokens"] == 500
        assert summary["token_totals"]["output_tokens"] == 120
        assert summary["usage_complete"] is True
    finally:
        active_metrics.reset(token)


def test_tool_response_failed_detection():
    assert tool_response_failed({"error": "BigQuery timed out"}) is True
    assert tool_response_failed({"success": False, "msg": "failed"}) is True
    assert tool_response_failed({"result": {"error": "Invalid table"}}) is True
    assert tool_response_failed([{"success": True}, {"error": "Sub-operation failed"}]) is True
    assert tool_response_failed({"success": True, "data": [1, 2, 3]}) is False


def test_ensure_agent_runs_table():
    mock_client = MagicMock()
    with patch("agents.runner.get_bigquery_client", return_value=mock_client):
        # Reset initialized flag
        import agents.runner as runner_mod
        runner_mod._AGENT_RUNS_TABLE_INITIALIZED = False

        ensure_agent_runs_table()
        assert mock_client.query.call_count >= 1
        assert "CREATE TABLE IF NOT EXISTS" in mock_client.query.call_args_list[0][0][0]


def test_persist_agent_run():
    mock_client = MagicMock()
    with patch("agents.runner.get_bigquery_client", return_value=mock_client), \
         patch("agents.runner.execute_query", return_value=[{"next_run_number": 2}]):
        metrics = InvestigationMetrics()
        metrics.status = "completed"
        metrics.duration_ms = 2500.0

        report = {
            "alert_id": "A101",
            "campaign_id": "CMP101",
            "status": "COMPLETE",
            "proposal": {"type": "TEST", "min_spend": 1250},
        }

        persist_agent_run(
            alert_id="A101",
            run_number=1,
            report=report,
            tool_calls=[{"tool": "get_campaign_terms", "duration_ms": 120.0}],
            batch_id="TEST_BATCH",
            execution_metrics=metrics,
            campaign_id="CMP101",
        )

        assert mock_client.query.call_count >= 1
        insert_sql = mock_client.query.call_args_list[-1][0][0]
        assert "INSERT INTO" in insert_sql
        job_config = mock_client.query.call_args_list[-1][1]["job_config"]
        params = {p.name: p.value for p in job_config.query_parameters}
        assert params["alert_id"] == "A101"
        assert params["recommendation"] == "TEST"
        assert params["confidence"] == "COMPLETE"
        assert params["run_number"] == 2
        assert params["batch_id"] == "TEST_BATCH"
