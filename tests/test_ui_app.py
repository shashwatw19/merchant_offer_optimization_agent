"""Tests for FastAPI UI application routes and evidence verification."""

import json
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


def test_api_evidence_verify_endpoint(client):
    mock_res = {
        "success": True,
        "evidence_ref": "bq:offers_silver.campaigns:CMP131",
        "target_type": "CAMPAIGN_TERMS",
        "source_layer": "BRONZE",
        "source_table": "offers_bronze.campaigns_raw",
        "resolved_id": "CMP131",
        "record_count": 1,
        "records": [{"campaign_id": "CMP131", "min_spend": "2000.00"}],
        "verification_verdict": "VERIFIED_SOURCE_RECORD",
    }
    with patch("services.evidence_service.EvidenceResolver.resolve_evidence", return_value=mock_res):
        response = client.get("/api/evidence/verify?ref=bq:offers_silver.campaigns:CMP131&campaign_id=CMP131")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["resolved_id"] == "CMP131"
        assert data["records"][0]["min_spend"] == "2000.00"


def test_view_report_route(client, monkeypatch):
    alert_id = "A9999"
    report_data = {
        "alert_id": alert_id,
        "campaign_id": "CMP131",
        "status": "COMPLETE",
        "summary": "Spice Route Kitchen threshold friction investigated.",
        "findings": [
            {
                "observation": "Redemption rate is 4.00%, below 5.00% threshold",
                "evidence": ["bq:offers_silver.campaigns:CMP131"],
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

    monkeypatch.setattr("ui.app._fetch_agent_run_report", lambda aid: report_data if aid == alert_id else None)

    response = client.get(f"/reports/{alert_id}")
    assert response.status_code == 200
    assert "Spice Route Kitchen threshold friction" in response.text
    assert "CMP131" in response.text
    assert "Agent Execution Summary" not in response.text
    assert "bq:offers_silver.campaigns:CMP131" in response.text

    # Test markdown download endpoint
    md_response = client.get(f"/reports/{alert_id}/markdown")
    assert md_response.status_code == 200
    assert "Merchant Offer Investigation Report" in md_response.text


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



def test_ui_admin_panel_page(client):
    response = client.get("/admin")
    assert response.status_code == 200
    assert "Admin Panel" in response.text
    assert "Batch averages" in response.text
    assert "Investigation execution metrics" in response.text


def test_ui_admin_investigations_api(client):
    mock_rows = [
        {
            "run_key": "exec_run_1",
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "run_number": 1,
            "recommendation": "TEST",
            "confidence": "COMPLETE",
            "run_status": "completed",
            "run_time_ist": "2026-11-18 10:00:00 IST",
            "duration_ms": 3200.0,
            "metrics_json": json.dumps({
                "schema_version": 1,
                "run_id": "exec_run_1",
                "status": "completed",
                "token_totals": {"total_tokens": 1500, "input_tokens": 1200, "output_tokens": 300},
            }),
        }
    ]
    with patch("ui.app.execute_query", return_value=mock_rows), \
         patch("ui.app.ensure_agent_runs_table", return_value=None):
        response = client.get("/api/admin/investigations?limit=25&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert "investigations" in data
        assert len(data["investigations"]) == 1
        assert data["investigations"][0]["alert_id"] == "A1001"
        assert data["investigations"][0]["execution_metrics"]["token_totals"]["total_tokens"] == 1500


def test_ui_admin_batch_averages_api(client):
    mock_batches = [
        {
            "batch_id": "OFFER_BATCH_01",
            "investigation_count": 5,
            "token_sample_count": 5,
            "avg_total_tokens": 2450.0,
            "duration_sample_count": 5,
            "avg_duration_ms": 3100.5,
        }
    ]
    with patch("ui.app.execute_query", return_value=mock_batches), \
         patch("ui.app.ensure_agent_runs_table", return_value=None):
        response = client.get("/api/admin/batch-averages")
        assert response.status_code == 200
        data = response.json()
        assert "batches" in data
        assert len(data["batches"]) == 1
        assert data["batches"][0]["batch_id"] == "OFFER_BATCH_01"
        assert data["batches"][0]["avg_total_tokens"] == 2450.0


def test_ui_admin_investigation_detail_api(client):
    mock_run = [
        {
            "run_key": "exec_run_1",
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "run_number": 1,
            "recommendation": "TEST",
            "confidence": "COMPLETE",
            "run_status": "completed",
            "run_time_ist": "2026-11-18 10:00:00 IST",
            "duration_ms": 3200.0,
            "metrics_json": json.dumps({
                "schema_version": 1,
                "run_id": "exec_run_1",
                "status": "completed",
                "token_totals": {"total_tokens": 1500},
                "model_calls": [{"model": "gemini-3.5-flash", "duration_ms": 2800.0}],
            }),
            "tool_calls_json": json.dumps([
                {"tool": "get_campaign_terms", "status": "success", "duration_ms": 150.0}
            ]),
        }
    ]
    with patch("ui.app.execute_query", return_value=mock_run), \
         patch("ui.app.ensure_agent_runs_table", return_value=None):
        response = client.get("/api/admin/investigations/exec_run_1")
        assert response.status_code == 200
        data = response.json()
        assert data["alert_id"] == "A1001"
        assert data["execution_metrics"]["token_totals"]["total_tokens"] == 1500
        assert len(data["tool_calls"]) == 1
        assert data["tool_calls"][0]["tool"] == "get_campaign_terms"


def test_api_evalhub_investigate_by_alert_id(client):
    mock_alert = {
        "alert_id": "ALT-28e1e8c1",
        "campaign_id": "CMP131",
        "merchant_id": "M001",
        "rule_id": "R1",
        "metric_name": "redemption_rate",
        "metric_value": 4.0,
        "threshold_value": 5.0,
        "status": "OPEN",
    }
    mock_result = {
        "success": True,
        "alert_id": "ALT-28e1e8c1",
        "campaign_id": "CMP131",
        "rule_id": "R1",
        "report": {
            "alert_id": "ALT-28e1e8c1",
            "campaign_id": "CMP131",
            "rule_id": "R1",
            "status": "COMPLETE",
            "summary": "Min spend ₹2,000 exceeds median ticket ₹850.",
            "findings": [
                {"observation": "Redemption rate is 4.0%.", "evidence": ["offers_gold.gold_campaign_results:CMP131"]}
            ],
            "hypotheses": [
                {"text": "Spend threshold friction", "status": "SUPPORTED", "rationale": "Median spend is ₹850."}
            ],
            "recommendations": [
                {
                    "action_type": "ADJUST_THRESHOLD",
                    "priority": "PRIMARY",
                    "parameter_changes": {"min_spend": 1000.0},
                    "expected_impact": "Lowers threshold to ₹1,000.",
                    "risk_level": "LOW",
                    "rationale": "Matches median spend.",
                }
            ],
            "evidence": [
                {"source": "offers_gold.gold_campaign_results", "record_id": "CMP131", "fact": "4.0% redemption"}
            ],
            "proposal": {"type": "TEST", "min_spend": 1000.0},
            "future_incremental_spend": None,
            "human_approval_required": True,
        },
        "tool_calls": [
            {"type": "call", "name": "get_campaign_terms", "args": {"campaign_id": "CMP131"}, "tool_call_id": "c1"},
            {"type": "response", "name": "get_campaign_terms", "response": "{'success': True}", "tool_call_id": "c1"},
            {"type": "call", "name": "validate_proposal", "args": {"proposed_min_spend": 500}, "tool_call_id": "c2"},
            {"type": "response", "name": "validate_proposal", "response": "{'allowed': False}", "tool_call_id": "c2"},
        ],
    }

    async def fake_process_alert(alert):
        assert alert["campaign_id"] == "CMP131"
        return mock_result

    with patch("ui.app._fetch_open_alert", return_value=mock_alert) as fetch_mock, \
         patch("ui.app.process_alert_async", side_effect=fake_process_alert):
        response = client.post("/api/evalhub/investigate", json={"alert_id": "ALT-28e1e8c1"})

    assert response.status_code == 200
    fetch_mock.assert_called_once_with("ALT-28e1e8c1")
    data = response.json()
    assert data["alert_id"] == "ALT-28e1e8c1"
    assert data["summary"] == "Min spend ₹2,000 exceeds median ticket ₹850."
    assert data["root_cause"] == "Spend threshold friction (Median spend is ₹850.)"
    assert data["findings"] == ["Redemption rate is 4.0%."]
    assert len(data["recommendations"]) == 1
    assert "ADJUST_THRESHOLD [min_spend=1000.0]" in data["recommendations"][0]
    assert data["evidence_used"] == [{"source": "offers_gold.gold_campaign_results", "record_id": "CMP131"}]
    assert data["tool_calls"] == [
        {
            "name": "get_campaign_terms",
            "arguments": {"campaign_id": "CMP131"},
            "result": "{'success': True}",
            "status": "success",
            "call_id": "c1",
        },
        {
            "name": "validate_proposal",
            "arguments": {"proposed_min_spend": 500},
            "result": "{'allowed': False}",
            "status": "success",
            "call_id": "c2",
        },
    ]


def test_api_evalhub_investigate_inline_payload_and_validation(client):
    mock_result = {
        "success": True,
        "report": {
            "alert_id": "A7348",
            "campaign_id": "CMP205",
            "summary": "Acquisition cannibalization detected.",
            "findings": [{"observation": "82% repeat customers.", "evidence": []}],
            "hypotheses": [{"text": "Audience leakage", "status": "SUPPORTED"}],
            "recommendations": [],
            "proposal": {"type": "INVESTIGATE", "rationale": "Exclude repeat buyers."},
            "evidence": [],
        },
        "tool_calls": [],
    }

    async def fake_process_alert(alert):
        assert alert["alert_id"] == "A7348"
        assert alert["campaign_id"] == "CMP205"
        assert alert["rule_id"] == "R3"
        return mock_result

    with patch("ui.app._fetch_open_alert") as fetch_mock, \
         patch("ui.app.process_alert_async", side_effect=fake_process_alert):
        res = client.post(
            "/api/evalhub/investigate",
            json={"input": {"alert_id": "A7348", "campaign_id": "CMP205", "rule_id": "R3"}},
        )
        assert res.status_code == 200
        fetch_mock.assert_not_called()
        body = res.json()
        assert body["recommendations"] == ["INVESTIGATE: Exclude repeat buyers."]

        bad_res = client.post("/api/evalhub/investigate", json={"alert_id": "bad/id"})
        assert bad_res.status_code == 400
