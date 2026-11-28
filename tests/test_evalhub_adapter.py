"""Unit tests for EvalHub response and payload normalization adapter."""

from services.evalhub_adapter import (
    extract_alert_input,
    extract_root_cause,
    format_evalhub_response,
    format_evidence_used,
    format_findings,
    format_recommendations,
    normalize_tool_calls_for_evalhub,
)


def test_extract_alert_input_variants():
    assert extract_alert_input({"alert_id": "ALT-1"}) == ("ALT-1", None)
    assert extract_alert_input({"input": "ALT-2"}) == ("ALT-2", None)

    aid, full = extract_alert_input(
        {"alert_id": {"alert_id": "ALT-3", "campaign_id": "CMP131", "rule_id": "R1"}}
    )
    assert aid == "ALT-3"
    assert full["campaign_id"] == "CMP131"
    assert full["status"] == "OPEN"

    aid2, full2 = extract_alert_input(
        {"alert_id": "ALT-4", "campaign_id": "CMP205", "rule_id": "R3"}
    )
    assert aid2 == "ALT-4"
    assert full2["rule_id"] == "R3"


def test_normalize_tool_calls_from_paired_trace_and_metrics_fallback():
    trace = [
        {"type": "call", "name": "get_campaign_terms", "args": {"campaign_id": "CMP131"}, "tool_call_id": "t1"},
        {"type": "call", "name": "get_campaign_performance", "args": {"campaign_id": "CMP131"}, "tool_call_id": "t2"},
        {"type": "response", "name": "get_campaign_terms", "response": "{'success': True}", "tool_call_id": "t1"},
        {"type": "response", "name": "get_campaign_performance", "response": "{'success': False, 'error': 'timeout'}", "tool_call_id": "t2"},
    ]
    normalized = normalize_tool_calls_for_evalhub(tool_calls_trace=trace)
    assert normalized == [
        {
            "name": "get_campaign_terms",
            "arguments": {"campaign_id": "CMP131"},
            "result": "{'success': True}",
            "status": "success",
            "call_id": "t1",
        },
        {
            "name": "get_campaign_performance",
            "arguments": {"campaign_id": "CMP131"},
            "result": "{'success': False, 'error': 'timeout'}",
            "status": "error",
            "call_id": "t2",
        },
    ]

    metrics_fallback = normalize_tool_calls_for_evalhub(
        tool_calls_trace=[],
        execution_metrics={
            "tool_calls": [
                {
                    "tool_call_id": "m1",
                    "tool": "get_spend_distribution",
                    "input": {"merchant_id": "M001"},
                    "output": {"median_txn_amount": 850.0},
                    "status": "success",
                }
            ]
        },
    )
    assert metrics_fallback == [
        {
            "name": "get_spend_distribution",
            "arguments": {"merchant_id": "M001"},
            "result": {"median_txn_amount": 850.0},
            "status": "success",
            "call_id": "m1",
        }
    ]


def test_format_evalhub_response_maps_full_dossier():
    result = {
        "success": True,
        "alert_id": "A1001",
        "campaign_id": "CMP131",
        "rule_id": "R1",
        "report": {
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "rule_id": "R1",
            "status": "COMPLETE",
            "summary": "Min spend too high.",
            "findings": [
                {"observation": "Redemption rate 4.0%", "evidence": ["offers_gold.gold_campaign_results:CMP131"]},
            ],
            "hypotheses": [
                {"text": "Spend threshold friction", "status": "SUPPORTED", "rationale": "Median bill ₹850"},
                {"text": "Delivery outage", "status": "REFUTED"},
            ],
            "recommendations": [
                {
                    "action_type": "ADJUST_THRESHOLD",
                    "parameter_changes": {"min_spend": 1000.0},
                    "expected_impact": "Lowers threshold to ₹1,000.",
                }
            ],
            "evidence": [
                {"source": "offers_gold.gold_campaign_results", "record_id": "CMP131", "fact": "4.0%"},
                {"source": "offers_gold.gold_campaign_results", "record_id": "CMP131", "fact": "duplicate"},
            ],
            "proposal": {"type": "TEST", "min_spend": 1000.0},
            "future_incremental_spend": None,
            "human_approval_required": True,
        },
        "tool_calls": [
            {"type": "call", "name": "validate_proposal", "args": {"proposed_min_spend": 1000.0}, "tool_call_id": "c1"},
            {"type": "response", "name": "validate_proposal", "response": "{'allowed': True}", "tool_call_id": "c1"},
        ],
    }

    out = format_evalhub_response(result)
    assert out["summary"] == "Min spend too high."
    assert out["root_cause"] == "Spend threshold friction (Median bill ₹850)"
    assert out["findings"] == ["Redemption rate 4.0%"]
    assert out["recommendations"] == ["ADJUST_THRESHOLD [min_spend=1000.0]: Lowers threshold to ₹1,000."]
    assert out["evidence_used"] == [{"source": "offers_gold.gold_campaign_results", "record_id": "CMP131"}]
    assert out["tool_calls"][0]["status"] == "success"
    assert out["future_incremental_spend"] is None
    assert out["human_approval_required"] is True
