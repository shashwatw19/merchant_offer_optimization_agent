import json
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from ui.app import app, REPORT_DIR


@pytest.fixture
def client():
    return TestClient(app)


def test_ui_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ui_dashboard_renders_single_alerts_table(client, monkeypatch):
    mock_alerts = [
        {
            "alert_id": "A_R1_CMP131_1",
            "campaign_id": "CMP131",
            "merchant_id": "M101",
            "rule_id": "R1",
            "metric_name": "redemption_rate",
            "metric_value": 0.032,
            "threshold_value": 0.05,
            "status": "OPEN",
            "created_at": "2026-11-16 10:00:00 IST",
        },
        {
            "alert_id": "A_R2_CMP140_1",
            "campaign_id": "CMP140",
            "merchant_id": "M102",
            "rule_id": "R2",
            "metric_name": "redemption_drop",
            "metric_value": 0.65,
            "threshold_value": 0.50,
            "status": "RESOLVED",
            "created_at": "2026-11-16 09:30:00 IST",
        },
    ]

    monkeypatch.setattr("ui.app._fetch_all_alerts", lambda limit=100: mock_alerts)

    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Verify single alerts table presence and header elements
    assert "data-table" in html
    assert "Trigger New Alerts" in html
    assert "A_R1_CMP131_1" in html
    assert "CMP131" in html
    assert "M101" in html
    assert "Low redemption rate" in html
    assert "A_R2_CMP140_1" in html
    assert "Investigate" in html


def test_ui_trigger_new_alerts_endpoint(client, monkeypatch):
    # Mock alert generation workflow
    mock_new_alerts = [
        {
            "alert_id": "A_R1_NEW_1",
            "campaign_id": "CMP999",
            "merchant_id": "M999",
            "rule_id": "R1",
            "metric_name": "redemption_rate",
            "metric_value": 0.02,
            "threshold_value": 0.05,
            "status": "OPEN",
        }
    ]

    with patch("alert.run_all_alerts", return_value=mock_new_alerts) as mock_run:
        with patch("alert.save_alerts_to_bigquery") as mock_save:
            response = client.post("/alerts/trigger", follow_redirects=False)
            assert response.status_code == 303
            assert "msg=triggered" in response.headers["location"]
            assert "count=1" in response.headers["location"]
            mock_run.assert_called_once()
            mock_save.assert_called_once()


def test_ui_view_report_workflow_and_campaign_comparison(client, tmp_path, monkeypatch):
    alert_id = "A_TEST_CMP131"
    report_file = tmp_path / f"report_{alert_id}.json"
    trace_file = tmp_path / f"trace_{alert_id}.json"

    sample_report = {
        "alert_id": alert_id,
        "campaign_id": "CMP131",
        "execution_id": "exec_test_123",
        "generated_at": "2026-11-16 12:00:00 IST",
        "status": "COMPLETE",
        "summary": "Lower minimum spend from 1500 to 1000 to capture modal order sizes.",
        "findings": [
            {
                "observation": "Redemption dropped below 4% due to ticket size threshold friction.",
                "evidence": ["bq:prj-imp-act-campaign.offers_silver.transactions:CMP131"],
            }
        ],
        "hypotheses": [
            {
                "text": "Spend distribution modal density is between ₹1000 and ₹1400",
                "status": "SUPPORTED",
                "rationale": "70% of transactions fall under ₹1500 threshold.",
            }
        ],
        "proposal": {
            "type": "TEST",
            "min_spend": 1000.0,
            "cashback_pct": 10.0,
            "cashback_cap": 200.0,
            "rationale": "Captures 35% more transactions with safe budget utilisation.",
        },
        "simulation_type": "HISTORICAL_REPLAY",
        "human_approval_required": True,
    }

    sample_trace = {
        "execution_id": "exec_test_123",
        "alert_id": alert_id,
        "campaign_id": "CMP131",
        "agent_name": "merchant_offer_optimization_agent",
        "model": "gemini-3.5-flash",
        "total_duration_ms": 2340.5,
        "tokens": {
            "input_tokens": 850,
            "output_tokens": 420,
            "total_tokens": 1270,
        },
        "steps": [
            {
                "step_number": 1,
                "agent": "merchant_offer_optimization_agent",
                "tool_name": "get_campaign_terms",
                "purpose": "Retrieve campaign discount structure, budget limits, minimum spend, and operational status.",
                "inputs": {"campaign_id": "CMP131"},
                "output_preview": "{'min_spend': 1500.0, 'cashback_pct': 10.0}",
                "duration_ms": 210.4,
                "status": "SUCCESS",
            },
            {
                "step_number": 2,
                "agent": "merchant_offer_optimization_agent",
                "tool_name": "get_spend_distribution",
                "purpose": "Analyze customer transaction spend distribution relative to minimum spend thresholds.",
                "inputs": {"campaign_id": "CMP131"},
                "output_preview": "{'p50': 1150.0, 'p75': 1380.0}",
                "duration_ms": 320.1,
                "status": "SUCCESS",
            },
            {
                "step_number": 3,
                "agent": "merchant_offer_optimization_agent",
                "tool_name": "simulate_campaign_change",
                "purpose": "Run deterministic historical replay simulation on past transactions to project financial impact.",
                "inputs": {"campaign_id": "CMP131", "proposed_min_spend": 1000.0},
                "output_preview": "{'additional_txns': 45, 'budget_safe': True}",
                "duration_ms": 450.8,
                "status": "SUCCESS",
            },
        ],
        "status": "SUCCESS",
    }

    report_file.write_text(json.dumps(sample_report), encoding="utf-8")
    trace_file.write_text(json.dumps(sample_trace), encoding="utf-8")

    monkeypatch.setattr("ui.app._report_path", lambda aid: report_file)
    monkeypatch.setattr("ui.app._trace_path", lambda aid: trace_file)

    # Mock original terms returned from BigQuery
    mock_terms = {
        "success": True,
        "campaign_id": "CMP131",
        "terms": {
            "campaign_id": "CMP131",
            "merchant_id": "M101",
            "objective": "ACQUIRE_NEW",
            "min_spend": 1500.0,
            "cashback_pct": 10.0,
            "cashback_cap": 200.0,
            "budget": 20000.0,
        },
    }
    monkeypatch.setattr("ui.app.get_campaign_terms", lambda cid: mock_terms)

    response = client.get(f"/reports/{alert_id}")
    assert response.status_code == 200
    html = response.text

    # 1. Campaign Terms vs. Agent Recommendations Verification
    assert "Campaign Terms vs. Agent Recommendations" in html
    assert "₹1500.00" in html
    assert "₹1000.00" in html
    assert "-₹500.00" in html
    assert "Strategic Justification &amp; Rationale" in html or "Strategic Justification & Rationale" in html
    assert "Captures 35% more transactions" in html

    # 2. Agent Workflow Visibility Verification
    assert "Agent Workflow &amp; Execution Observability" in html or "Agent Workflow & Execution Observability" in html
    assert "merchant_offer_optimization_agent" in html
    assert "gemini-3.5-flash" in html
    assert "1270 tokens" in html
    assert "In: 850 | Out: 420" in html
    assert "get_campaign_terms" in html
    assert "get_spend_distribution" in html
    assert "simulate_campaign_change" in html
    assert "210.4 ms" in html
    assert "SUCCESS" in html
