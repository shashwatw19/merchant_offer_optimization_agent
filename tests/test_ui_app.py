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
        assert "bq:offers_silver.campaigns:CMP131" in response.text

        # Test markdown download endpoint
        md_response = client.get(f"/reports/{alert_id}/markdown")
        assert md_response.status_code == 200
        assert "Merchant Offer Investigation Report" in md_response.text
    finally:
        if report_file.exists():
            report_file.unlink()
