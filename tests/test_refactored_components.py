"""Unit tests for P1 and P2 refactored architectural components."""

import pytest
from unittest.mock import MagicMock
from agents.playbooks import get_playbook, PlaybookR1, PlaybookR2, PlaybookR3, BasePlaybook
from agents.telemetry import ExecutionMetricsCollector
from services.alert_store import _get_alerts_columns, ensure_alert_table, fetch_pending_alerts, update_alert_status
from services.report_converter import convert_json_report_to_markdown
from services.gcs_storage import StorageResult


def test_playbook_resolver():
    pb_r1 = get_playbook("R1")
    assert isinstance(pb_r1, PlaybookR1)
    assert "Spend Friction" in pb_r1.get_investigation_methodology() or "LOW REDEMPTION" in pb_r1.get_investigation_methodology()

    pb_r2 = get_playbook("R2")
    assert isinstance(pb_r2, PlaybookR2)
    assert "OPERATIONAL DISRUPTION" in pb_r2.get_investigation_methodology() or "closure" in pb_r2.get_investigation_methodology().lower()

    pb_r3 = get_playbook("R3")
    assert isinstance(pb_r3, PlaybookR3)
    assert "CANNIBALIZATION" in pb_r3.get_investigation_methodology() or "TARGETING" in pb_r3.get_investigation_methodology()

    pb_default = get_playbook("UNKNOWN")
    assert isinstance(pb_default, BasePlaybook)


def test_playbook_prompt_generation():
    pb = get_playbook("R1")
    sys_inst = pb.build_system_instruction()
    assert "OPERATING PRINCIPLES" in sys_inst
    assert "Principal Merchant Offer Optimization Agent" in sys_inst

    task_prompt = pb.build_investigation_prompt({"alert_id": "A1001", "rule_id": "R1"})
    assert "A1001" in task_prompt
    assert "INVESTIGATION MANDATE" in task_prompt


def test_execution_metrics_collector():
    collector = ExecutionMetricsCollector(model_name="gemini-3.5-flash", alert_id="A1001")

    # Simulate an ADK event with usage metadata
    event_meta = MagicMock()
    event_meta.usage_metadata.prompt_token_count = 100
    event_meta.usage_metadata.candidates_token_count = 50
    event_meta.usage_metadata.total_token_count = 150
    event_meta.usage_metadata.cached_content_token_count = 10
    event_meta.usage_metadata.tool_use_prompt_token_count = 20
    event_meta.usage_metadata.thoughts_token_count = 5
    event_meta.content = None

    collector.process_event(event_meta)

    # Simulate a tool call and response
    part_call = MagicMock()
    part_call.function_call.name = "get_campaign_terms"
    part_call.function_call.args = {"campaign_id": "CMP131"}
    part_call.function_response = None
    part_call.text = None

    event_call = MagicMock()
    event_call.usage_metadata = None
    event_call.content.parts = [part_call]
    collector.process_event(event_call)

    part_resp = MagicMock()
    part_resp.function_call = None
    part_resp.function_response.name = "get_campaign_terms"
    part_resp.function_response.response = {"terms": {}}
    part_resp.text = None

    event_resp = MagicMock()
    event_resp.usage_metadata = None
    event_resp.content.parts = [part_resp]
    collector.process_event(event_resp)

    # Simulate final text
    part_text = MagicMock()
    part_text.function_call = None
    part_text.function_response = None
    part_text.text = '{"status": "COMPLETE"}'

    event_text = MagicMock()
    event_text.usage_metadata = None
    event_text.content.parts = [part_text]
    collector.process_event(event_text)

    metrics = collector.compute_metrics()
    assert metrics["prompt_tokens"] == 100
    assert metrics["candidates_tokens"] == 50
    assert metrics["tool_use_tokens"] == 20
    assert metrics["thoughts_tokens"] == 5
    assert metrics["input_tokens"] == 120
    assert metrics["output_tokens"] == 55
    assert metrics["total_tokens"] == 150
    assert metrics["tool_call_count"] == 1
    assert metrics["model"] == "gemini-3.5-flash"
    assert collector.final_text == '{"status": "COMPLETE"}'


def test_report_converter_direct(sample_report_dict=None, monkeypatch=None):
    mock_storage = MagicMock()
    mock_storage.upload_markdown.return_value = StorageResult(
        success=True,
        uri="gs://test-bucket/reports/markdown/exec_A1001.md",
        bucket="test-bucket",
        object_name="reports/markdown/exec_A1001.md",
        content_type="text/markdown",
    )
    import services.report_converter as rc_mod
    if monkeypatch:
        monkeypatch.setattr(rc_mod, "get_storage_service", lambda: mock_storage)

    report_payload = {
        "alert_id": "A1001",
        "campaign_id": "CMP131",
        "status": "COMPLETE",
        "summary": "Sample summary",
    }
    res = convert_json_report_to_markdown(report_data=report_payload, save_to_gcs=False)
    assert res["success"] is True
    assert res["alert_id"] == "A1001"
    assert "# Merchant Offer Investigation Report" in res["markdown_content"]


def test_record_agent_run_success(monkeypatch):
    from services.run_store import record_agent_run
    import core.bigquery_client as bq_mod

    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_client.load_table_from_json.return_value = mock_job
    monkeypatch.setattr(bq_mod, "get_bigquery_client", lambda project=None: mock_client)

    success = record_agent_run(
        execution_id="exec_test_123",
        alert_id="A1001",
        campaign_id="CMP131",
        status="SUCCESS",
        metrics={"duration_ms": 1200.0, "total_tokens": 500, "input_tokens": 400, "output_tokens": 100},
        tool_calls=[{"name": "get_campaign_terms", "type": "call"}],
    )
    assert success is True
    assert mock_client.load_table_from_json.called
    assert mock_job.result.called


def test_record_agent_run_fallback_streaming(monkeypatch):
    from services.run_store import record_agent_run
    import core.bigquery_client as bq_mod

    mock_client = MagicMock()
    mock_client.load_table_from_json.side_effect = RuntimeError("Batch load error")
    mock_client.insert_rows_json.return_value = []  # No errors
    monkeypatch.setattr(bq_mod, "get_bigquery_client", lambda project=None: mock_client)

    success = record_agent_run(
        execution_id="exec_test_fallback",
        alert_id="A1001",
        campaign_id="CMP131",
        status="SUCCESS",
        metrics={"duration_ms": 1500.0},
    )
    assert success is True
    assert mock_client.insert_rows_json.called


def test_fetch_agent_runs(monkeypatch):
    from services.run_store import fetch_agent_runs
    import core.bigquery_client as bq_mod

    mock_rows = [
        {"execution_id": "exec_01", "alert_id": "A1001", "status": "SUCCESS"}
    ]
    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None: mock_rows)

    runs = fetch_agent_runs(limit=5, alert_id="A1001")
    assert len(runs) == 1
    assert runs[0]["execution_id"] == "exec_01"


def test_tool_tokens_reconciled_when_zero():
    collector = ExecutionMetricsCollector(model_name="gemini-3.5-flash", alert_id="A1001")

    # Event with 0 tool_use tokens reported by LLM
    event_meta = MagicMock()
    event_meta.usage_metadata.prompt_token_count = 500
    event_meta.usage_metadata.candidates_token_count = 200
    event_meta.usage_metadata.total_token_count = 700
    event_meta.usage_metadata.cached_content_token_count = 0
    event_meta.usage_metadata.tool_use_prompt_token_count = 0
    event_meta.usage_metadata.thoughts_token_count = 0
    event_meta.content = None
    collector.process_event(event_meta)

    # Tool call with payload
    collector.tool_calls_trace = [
        {"type": "call", "name": "get_campaign_performance", "args": {"campaign_id": "CMP131"}},
        {"type": "response", "name": "get_campaign_performance", "response": "a" * 800, "duration_ms": 100},
    ]
    metrics = collector.compute_metrics()
    assert metrics["tool_use_tokens"] > 0
    assert metrics["tool_used_token"] == metrics["tool_use_tokens"]


def test_update_agent_run_gcs_uris(monkeypatch):
    from services.run_store import update_agent_run_gcs_uris
    import core.bigquery_client as bq_mod

    executed_queries = []
    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None: executed_queries.append((sql, parameters)))

    ok = update_agent_run_gcs_uris(
        execution_id="exec_A1001_123_run1",
        gcs_json_uri="gs://bucket/report.json",
        gcs_markdown_uri="gs://bucket/report.md",
    )
    assert ok is True
    assert len(executed_queries) == 1
    assert "UPDATE" in executed_queries[0][0]


def test_get_next_run_number_and_generate_id(monkeypatch):
    from services.run_store import get_next_run_number, generate_execution_id
    import core.bigquery_client as bq_mod

    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None, timeout_sec=None: [{"total_runs": 2}])

    next_run = get_next_run_number("A8247")
    assert next_run == 3

    exec_id = generate_execution_id("A8247", run_number=next_run)
    assert "exec_A8247_" in exec_id
    assert exec_id.endswith("_run3")



