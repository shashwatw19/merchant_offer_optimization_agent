import json
from unittest.mock import MagicMock
import pytest
from agents.tools.report_tools import convert_json_report_to_markdown
from services.gcs_storage import StorageResult


@pytest.fixture
def sample_report():
    return {
        "alert_id": "A4004",
        "campaign_id": "CMP400",
        "status": "COMPLETE",
        "summary": "Sample test report.",
        "findings": [{"observation": "Test observation", "evidence": ["bq:table"]}],
        "hypotheses": [{"text": "Test hyp", "status": "SUPPORTED"}],
        "proposal": {"type": "TEST", "min_spend": 1500, "cashback_pct": 10, "cashback_cap": 200},
        "simulation_type": "HISTORICAL_REPLAY",
        "future_incremental_spend": None,
        "human_approval_required": True,
    }


def test_tool_with_in_memory_data(sample_report, monkeypatch):
    mock_storage = MagicMock()
    mock_storage.upload_markdown.return_value = StorageResult(
        success=True,
        uri="gs://test-bucket/reports/markdown/exec_A4004.md",
        bucket="test-bucket",
        object_name="reports/markdown/exec_A4004.md",
        content_type="text/markdown",
    )
    monkeypatch.setattr("agents.tools.report_tools.get_storage_service", lambda: mock_storage)

    res = convert_json_report_to_markdown(report_data=sample_report, save_to_gcs=True)
    assert res["success"] is True
    assert res["alert_id"] == "A4004"
    assert "A4004" in res["markdown_content"]
    assert "# Merchant Offer Investigation Report" in res["markdown_content"]
    assert res["gcs_uri"] == "gs://test-bucket/reports/markdown/exec_A4004.md"


def test_tool_with_local_file(sample_report, tmp_path, monkeypatch):
    json_file = tmp_path / "test_report.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(sample_report, f)

    out_md = tmp_path / "output.md"
    mock_storage = MagicMock()
    mock_storage.upload_markdown.return_value = StorageResult(
        success=True,
        uri="gs://test-bucket/reports/markdown/exec.md",
        bucket="test-bucket",
        object_name="reports/markdown/exec.md",
        content_type="text/markdown",
    )
    monkeypatch.setattr("agents.tools.report_tools.get_storage_service", lambda: mock_storage)

    res = convert_json_report_to_markdown(
        json_path=str(json_file),
        output_path=str(out_md),
        save_to_gcs=True,
    )
    assert res["success"] is True
    assert out_md.exists()
    assert "A4004" in open(out_md, "r", encoding="utf-8").read()


def test_tool_with_gcs_uri(sample_report, monkeypatch):
    mock_storage = MagicMock()
    mock_storage.download_json.return_value = sample_report
    mock_storage.upload_markdown.return_value = StorageResult(
        success=True,
        uri="gs://test-bucket/reports/markdown/exec.md",
        bucket="test-bucket",
        object_name="reports/markdown/exec.md",
        content_type="text/markdown",
    )
    monkeypatch.setattr("agents.tools.report_tools.get_storage_service", lambda: mock_storage)

    res = convert_json_report_to_markdown(
        gcs_uri="gs://test-bucket/reports/json/report.json",
        save_to_gcs=True,
    )
    assert res["success"] is True
    assert mock_storage.download_json.called
    assert res["alert_id"] == "A4004"


def test_tool_missing_input():
    res = convert_json_report_to_markdown()
    assert res["success"] is False
    assert "One of 'report_data', 'json_path', or 'gcs_uri'" in res["error"]


def test_tool_nonexistent_local_file():
    res = convert_json_report_to_markdown(json_path="nonexistent_report_xyz.json")
    assert res["success"] is False
    assert "not found" in res["error"]
