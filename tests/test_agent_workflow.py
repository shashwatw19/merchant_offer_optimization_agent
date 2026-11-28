import pytest
from agents.agent import (
    agent,
    extract_json_report,
    get_or_create_session,
    _enrich_dossier_from_traces,
    get_runner_for_rule,
    USER_ID,
)
from agents.tracer import ExecutionTracer


def test_rule_specialized_runners():
    # Verify runners specialize instructions by rule_id
    runner_r1 = get_runner_for_rule("R1")
    runner_r2 = get_runner_for_rule("R2")
    runner_r3 = get_runner_for_rule("R3")
    runner_default = get_runner_for_rule("DEFAULT")

    # 1. Distinct agents with specialized system instructions
    assert "PLAYBOOK R1" in runner_r1.agent.instruction
    assert "PLAYBOOK R2" not in runner_r1.agent.instruction

    assert "PLAYBOOK R2" in runner_r2.agent.instruction
    assert "PLAYBOOK R1" not in runner_r2.agent.instruction

    assert "PLAYBOOK R3" in runner_r3.agent.instruction
    assert "PLAYBOOK R1" not in runner_r3.agent.instruction

    # 2. Default runner contains master instruction
    assert "PLAYBOOK R1" in runner_default.agent.instruction
    assert "PLAYBOOK R2" in runner_default.agent.instruction
    assert "PLAYBOOK R3" in runner_default.agent.instruction

    # 3. Cache identity and alias normalization
    assert get_runner_for_rule("R1") is runner_r1
    assert get_runner_for_rule("rule_1") is runner_r1
    assert get_runner_for_rule("RULE-2") is runner_r2
    assert get_runner_for_rule({"rule": "R3"}) is runner_r3


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


def test_session_lifecycle_and_isolation():
    import asyncio
    async def _run():
        session1 = await get_or_create_session(USER_ID, "session_alert_A1001")
        session2 = await get_or_create_session(USER_ID, "session_alert_A1002")
        assert session1.id != session2.id

        # Re-retrieving the same session ID returns the existing session
        session1_again = await get_or_create_session(USER_ID, "session_alert_A1001")
        assert session1.id == session1_again.id
    asyncio.run(_run())


def test_tracer_writes_valid_jsonl(tmp_path):
    tracer = ExecutionTracer(trace_dir=str(tmp_path))
    trace_file = tracer.write_trace(
        alert_id="A1001",
        campaign_id="CMP131",
        model="gemini-2.5-flash",
        tool_calls=[{"name": "get_campaign_terms", "type": "call"}],
        report={"alert_id": "A1001"},
        duration_ms=125.5,
        playbook="R1",
    )
    assert trace_file.exists()
    with open(trace_file, "r", encoding="utf-8") as f:
        line = f.readline()
        assert "A1001" in line
        assert "CMP131" in line
        assert "get_campaign_terms" in line
        assert '"playbook": "R1"' in line


def test_enrich_dossier_from_traces_populates_empty_sections():
    sample_alert = {"alert_id": "ALT-28e1e8c1", "campaign_id": "CMP131", "rule_id": "R1"}
    sample_traces = [
        {"type": "response", "name": "get_campaign_terms", "response": "{'terms': {'min_spend': 2000.0, 'cashback_pct': 10.0, 'cashback_cap': 200.0, 'merchant_id': 'M001'}}"},
        {"type": "response", "name": "get_campaign_performance", "response": "{'performance': {'redemption_rate': 4.0, 'targeted_customer_count': 150, 'delivered_customer_count': 141, 'redeeming_customer_count': 6}}"},
        {"type": "response", "name": "get_spend_distribution", "response": "{'spend_profile': {'merchant_name': 'Spice Route Kitchen', 'merchant_city': 'Pune', 'median_txn_amount': 850.0, 'avg_txn_amount': 882.32}}"},
        {"type": "response", "name": "get_delivery_metrics", "response": "{'delivery_metrics': {'city_mismatch_pct': 61.33, 'out_of_city_customers': 92}}"},
        {"type": "call", "name": "validate_proposal", "args": {"proposed_min_spend": 1000}}
    ]
    # Input with empty hypotheses and fallback recommendations
    input_report = {
        "summary": "Investigation for CMP131 â‚¹2,000 threshold friction.",
        "findings": [{"observation": "Alert ALT-28e1e8c1 investigated for campaign CMP131.", "evidence": ["rule:R1"]}],
        "hypotheses": [],
        "recommendations": [{"action_type": "MONITOR_VELOCITY", "priority": "PRIMARY", "expected_impact": "Track post-period velocity", "risk_level": "LOW", "rationale": "Review raw findings."}],
    }
    dossier = _enrich_dossier_from_traces(
        parsed=input_report,
        alert=sample_alert,
        tool_calls_trace=sample_traces,
        final_text="",
        exec_id="exec_test",
        now_str="2026-11-20 00:00:00",
        metrics={},
    )
    # 1. Hypotheses must be populated with supported root causes
    assert len(dossier["hypotheses"]) >= 2
    assert any("Spend Barrier" in h["text"] for h in dossier["hypotheses"])
    assert any("Geographic" in h["text"] for h in dossier["hypotheses"])
    assert all(h["status"] in ("SUPPORTED", "REFUTED", "UNVERIFIED") for h in dossier["hypotheses"])

    # 2. Recommendations must include ADJUST_THRESHOLD and TARGETING_OVERHAUL
    action_types = [r["action_type"] for r in dossier["recommendations"]]
    assert "ADJUST_THRESHOLD" in action_types
    assert "TARGETING_OVERHAUL" in action_types

    # 3. Currency symbols must be clean rupees
    assert "â‚¹" not in dossier["summary"]
    assert "₹" in dossier["summary"]

    # 4. Findings and evidence must contain real citations
    assert len(dossier["findings"]) >= 2
    assert len(dossier["evidence"]) >= 2

    # 5. Rule and playbook tracking
    assert dossier["rule_id"] == "R1"
    assert dossier["playbook"] == "R1"

