"""Tests for FastAPI UI application routes and evidence verification."""

import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from ui.app import app


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ui_dashboard_route_renders_table(client):
    mock_alerts = [
        {
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "merchant_id": "M001",
            "rule_id": "R1",
            "metric_name": "redemption_rate",
            "metric_value": 4.0,
            "threshold_value": 5.0,
            "status": "OPEN",
            "created_at": "2026-11-16 10:00:00",
            "resolved_at": None,
            "investigation_summary": None,
        }
    ]
    with patch("ui.app._fetch_alerts", return_value=mock_alerts), \
         patch("ui.app._fetch_alert_status_counts", return_value={"OPEN": 1, "ALL": 1, "RESOLVED": 0, "PROCESSING": 0, "ERROR": 0}):
        response = client.get("/?status=OPEN")
        assert response.status_code == 200
        assert "Alert Management Queue" in response.text
        assert "A1001" in response.text
        assert "CMP131" in response.text
        assert "table" in response.text


@pytest.mark.skip(reason="Evidence verification API route deferred by user request")
def test_api_evidence_verify_endpoint(client):
    mock_res = {
        "success": True,
        "evidence_ref": "bq:card_silver.campaigns:CMP131",
        "target_type": "CAMPAIGN_TERMS",
        "source_layer": "BRONZE",
        "source_table": "card_bronze.campaigns_raw",
        "resolved_id": "CMP131",
        "record_count": 1,
        "records": [{"campaign_id": "CMP131", "min_spend": "2000.00"}],
        "verification_verdict": "VERIFIED_SOURCE_RECORD",
    }
    with patch("services.evidence_service.EvidenceResolver.resolve_evidence", return_value=mock_res):
        response = client.get("/api/evidence/verify?ref=bq:card_silver.campaigns:CMP131&campaign_id=CMP131")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["resolved_id"] == "CMP131"
        assert data["records"][0]["min_spend"] == "2000.00"


def test_view_report_route(client, tmp_path):
    alert_id = "A9999"
    report_data = {
        "alert_id": alert_id,
        "campaign_id": "CMP131",
        "status": "COMPLETE",
        "summary": "Spice Route Kitchen threshold friction investigated.",
        "findings": [
            {
                "observation": "Redemption rate is 4.00%, below 5.00% threshold",
                "evidence": ["bq:card_silver.campaigns:CMP131"],
            }
        ],
        "hypotheses": [
            {"text": "Spend threshold is restrictive", "status": "SUPPORTED"}
        ],
        "proposal": {"type": "TEST", "min_spend": 1500, "cashback_pct": 10},
        "simulation_type": "HISTORICAL_REPLAY",
        "human_approval_required": True,
        "metrics": {
            "duration_ms": 3500.0,
            "total_tokens": 2800,
            "prompt_tokens": 2200,
            "candidates_tokens": 600,
            "tool_call_count": 4,
            "model": "gemini-3.5-flash",
        },
    }

    report_file = Path("output/ui_reports") / f"report_{alert_id}.json"
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report_data), encoding="utf-8")

    try:
        response = client.get(f"/reports/{alert_id}")
        assert response.status_code == 200
        assert "Spice Route Kitchen threshold friction" in response.text
        assert "CMP131" in response.text
        assert "2,800" in response.text  # Total tokens formatted
        assert "gemini-3.5-flash" in response.text
        assert "bq:card_silver.campaigns:CMP131" in response.text

        # Test markdown download endpoint
        md_response = client.get(f"/reports/{alert_id}/markdown")
        assert md_response.status_code == 200
        assert "Merchant Offer Investigation Report" in md_response.text
    finally:
        if report_file.exists():
            report_file.unlink()


def test_build_execution_steps_parallel_tool_calls():
    from ui.app import _build_execution_steps

    # Simulated trace of 9 tool calls including 3 pairs of parallel invocations
    raw_trace = [
        # Pair 1: Parallel calls
        {"type": "call", "name": "get_campaign_terms", "args": {"campaign_id": "CMP410"}},
        {"type": "call", "name": "get_campaign_performance", "args": {"campaign_id": "CMP410"}},
        {"type": "response", "name": "get_campaign_terms", "duration_ms": 2055.37, "response": {"success": True, "terms": {}}},
        {"type": "response", "name": "get_campaign_performance", "duration_ms": 2055.39, "response": {"success": True, "performance": {}}},

        # Pair 2: Parallel calls
        {"type": "call", "name": "get_spend_distribution", "args": {"merchant_id": "M004"}},
        {"type": "call", "name": "get_delivery_metrics", "args": {"campaign_id": "CMP410"}},
        {"type": "response", "name": "get_spend_distribution", "duration_ms": 1874.78, "response": {"success": True, "spend_profile": {}}},
        {"type": "response", "name": "get_delivery_metrics", "duration_ms": 1874.77, "response": {"success": True, "delivery_metrics": {}}},

        # Pair 3: Parallel calls
        {"type": "call", "name": "get_customer_reviews", "args": {"merchant_id": "M004"}},
        {"type": "call", "name": "get_merchant_feedback", "args": {"merchant_id": "M004"}},
        {"type": "response", "name": "get_customer_reviews", "duration_ms": 1584.50, "response": {"success": True, "reviews": []}},
        {"type": "response", "name": "get_merchant_feedback", "duration_ms": 1584.56, "response": {"success": True, "feedback": []}},

        # Sequential calls
        {"type": "call", "name": "get_comparable_campaigns", "args": {"campaign_id": "CMP410"}},
        {"type": "response", "name": "get_comparable_campaigns", "duration_ms": 1300.90, "response": {"success": True, "peer_campaigns": []}},

        {"type": "call", "name": "validate_proposal", "args": {"proposed_min_spend": 1000}},
        {"type": "response", "name": "validate_proposal", "duration_ms": 2.07, "response": {"allowed": True}},

        {"type": "call", "name": "simulate_campaign_change", "args": {"campaign_id": "CMP410", "min_spend": 1000}},
        {"type": "response", "name": "simulate_campaign_change", "duration_ms": 1204.25, "response": {"success": True, "simulation_type": "HISTORICAL_REPLAY"}},
    ]

    steps = _build_execution_steps(raw_trace)

    # Must be exactly 9 steps, not 12
    assert len(steps) == 9

    # Each step must have its arguments, response, and duration attached
    expected_tools = [
        ("get_campaign_terms", 2055.37, {"campaign_id": "CMP410"}),
        ("get_campaign_performance", 2055.39, {"campaign_id": "CMP410"}),
        ("get_spend_distribution", 1874.78, {"merchant_id": "M004"}),
        ("get_delivery_metrics", 1874.77, {"campaign_id": "CMP410"}),
        ("get_customer_reviews", 1584.50, {"merchant_id": "M004"}),
        ("get_merchant_feedback", 1584.56, {"merchant_id": "M004"}),
        ("get_comparable_campaigns", 1300.90, {"campaign_id": "CMP410"}),
        ("validate_proposal", 2.07, {"proposed_min_spend": 1000}),
        ("simulate_campaign_change", 1204.25, {"campaign_id": "CMP410", "min_spend": 1000}),
    ]

    for i, (tool_name, latency, expected_args) in enumerate(expected_tools, start=1):
        step = steps[i - 1]
        assert step["step_number"] == i
        assert step["tool_name"] == tool_name
        assert step["duration_ms"] == latency
        assert step["args"] == expected_args
        assert step["status"] == "SUCCESS"
        assert len(step["response_summary"]) > 0

