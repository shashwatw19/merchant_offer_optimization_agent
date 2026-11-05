import pytest
from agents.agent import (
    agent,
    extract_json_report,
    get_or_create_session,
    USER_ID,
    APP_NAME,
)
from agents.tracer import ExecutionTracer


def test_agent_tool_registration():
    # Verify all 9 approved tools are registered with ADK LlmAgent
    registered_tool_names = [getattr(t, "__name__", str(t)) for t in agent.tools]
    assert "get_campaign_terms" in registered_tool_names
    assert "get_campaign_performance" in registered_tool_names
    assert "get_spend_distribution" in registered_tool_names
    assert "get_customer_reviews" in registered_tool_names
    assert "get_merchant_feedback" in registered_tool_names
    assert "get_delivery_metrics" in registered_tool_names
    assert "get_comparable_campaigns" in registered_tool_names
    assert "validate_proposal" in registered_tool_names
    assert "simulate_campaign_change" in registered_tool_names
    assert len(registered_tool_names) == 9


def test_extract_json_report_from_markdown():
    sample_text = """
    Here is my analysis of the alert:
    ```json
    {
      "alert_id": "A1001",
      "campaign_id": "CMP131",
      "status": "COMPLETE",
      "findings": [
        {"observation": "Low redemption rate 4%", "evidence": ["bq:gold_results"]}
      ],
      "hypotheses": [
        {"text": "Friction in minimum spend threshold", "status": "SUPPORTED"}
      ],
      "proposal": {
        "type": "TEST",
        "min_spend": 1500,
        "cashback_pct": 10,
        "cashback_cap": 200
      },
      "simulation_type": "HISTORICAL_REPLAY",
      "future_incremental_spend": null,
      "human_approval_required": true,
      "summary": "Propose testing ₹1500 min spend."
    }
    ```
    """
    report = extract_json_report(sample_text)
    assert report is not None
    assert report["alert_id"] == "A1001"
    assert report["proposal"]["min_spend"] == 1500
    assert report["human_approval_required"] is True


def test_extract_json_report_handles_malformed_text():
    invalid_text = "I am an agent but forgot to output JSON."
    report = extract_json_report(invalid_text)
    assert report is None


@pytest.mark.asyncio
async def test_session_lifecycle_and_isolation():
    session1 = await get_or_create_session(USER_ID, "session_alert_A1001")
    session2 = await get_or_create_session(USER_ID, "session_alert_A1002")
    assert session1.id != session2.id

    # Re-retrieving the same session ID returns the existing session
    session1_again = await get_or_create_session(USER_ID, "session_alert_A1001")
    assert session1.id == session1_again.id


def test_tracer_writes_valid_jsonl(tmp_path):
    tracer = ExecutionTracer(trace_dir=str(tmp_path))
    trace_file = tracer.write_trace(
        alert_id="A1001",
        campaign_id="CMP131",
        model="gemini-2.5-flash",
        tool_calls=[{"name": "get_campaign_terms", "type": "call"}],
        report={"alert_id": "A1001"},
        duration_ms=125.5,
    )
    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        line = f.readline()
        assert "A1001" in line
        assert "CMP131" in line
        assert "get_campaign_terms" in line
