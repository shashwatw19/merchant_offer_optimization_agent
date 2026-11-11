import json
from unittest.mock import AsyncMock
import pytest
from agents.run_alert_pipeline import process_alert_batch


@pytest.mark.asyncio
async def test_process_alert_batch_success(tmp_path, monkeypatch):
    mock_alerts = [
        {
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "rule_id": "R1",
            "status": "OPEN",
        }
    ]

    mock_result = {
        "success": True,
        "alert_id": "A1001",
        "campaign_id": "CMP131",
        "report": {
            "alert_id": "A1001",
            "campaign_id": "CMP131",
            "status": "COMPLETE",
            "summary": "Spice Route Kitchen threshold friction investigated.",
            "findings": [{"observation": "4% redemption", "evidence": ["bq:gold_results"]}],
            "hypotheses": [{"text": "Threshold restrictive", "status": "SUPPORTED"}],
            "proposal": {"type": "TEST", "min_spend": 1500},
            "simulation_type": "HISTORICAL_REPLAY",
            "future_incremental_spend": None,
            "human_approval_required": True,
        },
    }

    import agents.run_alert_pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "process_alert_async", AsyncMock(return_value=mock_result))
    monkeypatch.setattr(pipeline_mod, "update_alert_status", lambda aid, status, summary=None: True)

    results = await process_alert_batch(mock_alerts, output_dir=tmp_path, dry_run=False)
    assert len(results) == 1
    assert results[0]["success"] is True

    # Report file created
    report_file = tmp_path / "report_A1001.json"
    assert report_file.exists()
    with open(report_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["alert_id"] == "A1001"
        assert data["proposal"]["min_spend"] == 1500

    # Markdown report file also created
    md_file = tmp_path / "report_A1001.md"
    assert md_file.exists()
    with open(md_file, "r", encoding="utf-8") as f:
        md_text = f.read()
        assert "A1001" in md_text
        assert "CMP131" in md_text
        assert "# Merchant Offer Investigation Report" in md_text

    # Result contains storage URIs
    assert "gcs_json_uri" in results[0]
    assert "gcs_markdown_uri" in results[0]


@pytest.mark.asyncio
async def test_process_alert_batch_error_handling(tmp_path, monkeypatch):
    mock_alerts = [
        {
            "alert_id": "A9999",
            "campaign_id": "CMP999",
            "rule_id": "R1",
            "status": "OPEN",
        }
    ]

    mock_fail = {
        "success": False,
        "alert_id": "A9999",
        "campaign_id": "CMP999",
        "error": "LLM quota exceeded",
    }

    status_updates = []

    import agents.run_alert_pipeline as pipeline_mod
    monkeypatch.setattr(pipeline_mod, "process_alert_async", AsyncMock(return_value=mock_fail))
    monkeypatch.setattr(pipeline_mod, "update_alert_status", lambda aid, status, summary=None: status_updates.append((aid, status)))

    results = await process_alert_batch(mock_alerts, output_dir=tmp_path, dry_run=False)
    assert len(results) == 1
    assert results[0]["success"] is False
    assert ("A9999", "ERROR") in status_updates
