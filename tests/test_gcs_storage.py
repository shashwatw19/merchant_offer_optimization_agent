import json
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from google.api_core import exceptions as g_exceptions

from services.gcs_storage import (
    GCSStorageService,
    StorageResult,
    get_storage_client,
    set_storage_client,
)


@pytest.fixture
def mock_storage_client():
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()

    client.bucket.return_value = bucket
    bucket.blob.return_value = blob

    # Default blob behavior
    blob.exists.return_value = True
    blob.download_as_text.return_value = json.dumps({"alert_id": "A1001", "status": "COMPLETE"})

    return client, bucket, blob


def test_build_object_path():
    service = GCSStorageService(bucket_name="test-bucket")
    fixed_date = datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)
    path = service.build_object_path("json", "exec_A1001_123", "json", date=fixed_date)
    assert path == "reports/json/2026/11/11/exec_A1001_123.json"

    md_path = service.build_object_path("markdown", "exec_A1001_123", ".md", date=fixed_date)
    assert md_path == "reports/markdown/2026/11/11/exec_A1001_123.md"


def test_upload_json_to_mock_gcs(mock_storage_client):
    client, bucket, blob = mock_storage_client
    service = GCSStorageService(bucket_name="test-bucket", client=client)

    data = {"alert_id": "A1001", "campaign_id": "CMP131", "status": "COMPLETE"}
    res = service.upload_json(
        report_data=data,
        execution_id="exec_test_01",
        alert_id="A1001",
        campaign_id="CMP131",
    )

    assert res.success is True
    assert res.is_fallback is False
    assert "gs://test-bucket/reports/json/" in res.uri
    assert blob.upload_from_string.called
    assert blob.metadata["alert_id"] == "A1001"
    assert blob.metadata["execution_id"] == "exec_test_01"


def test_upload_markdown_to_mock_gcs(mock_storage_client):
    client, bucket, blob = mock_storage_client
    service = GCSStorageService(bucket_name="test-bucket", client=client)

    md_content = "# Title\n\nContent here."
    res = service.upload_markdown(
        markdown_text=md_content,
        execution_id="exec_test_02",
        alert_id="A1001",
        campaign_id="CMP131",
    )

    assert res.success is True
    assert res.is_fallback is False
    assert "gs://test-bucket/reports/markdown/" in res.uri
    assert blob.upload_from_string.called
    assert blob.metadata["report_type"] == "INVESTIGATION_MARKDOWN"


def test_download_json_and_text(mock_storage_client):
    client, bucket, blob = mock_storage_client
    blob.download_as_text.return_value = '{"alert_id": "A1001", "score": 99}'

    service = GCSStorageService(bucket_name="test-bucket", client=client)
    downloaded = service.download_json("reports/json/2026/11/11/exec_01.json")
    assert downloaded["alert_id"] == "A1001"
    assert downloaded["score"] == 99

    text = service.download_text("gs://test-bucket/reports/markdown/2026/11/11/exec_01.md")
    assert "alert_id" in text


def test_object_exists(mock_storage_client):
    client, bucket, blob = mock_storage_client
    blob.exists.return_value = True

    service = GCSStorageService(bucket_name="test-bucket", client=client)
    assert service.object_exists("reports/json/exec.json") is True

    blob.exists.return_value = False
    assert service.object_exists("reports/json/missing.json") is False


def test_transient_error_retries_and_succeeds(mock_storage_client, monkeypatch):
    client, bucket, blob = mock_storage_client
    attempts = 0

    def flaky_upload(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise g_exceptions.ServiceUnavailable("GCS 503 Backend Error")
        return None

    blob.upload_from_string.side_effect = flaky_upload
    monkeypatch.setattr("time.sleep", lambda s: None)

    service = GCSStorageService(bucket_name="test-bucket", client=client)
    res = service.upload_json({"test": True}, execution_id="exec_retry_01")

    assert res.success is True
    assert res.is_fallback is False
    assert attempts == 2


def test_local_fallback_on_unreachable_gcs(tmp_path, monkeypatch):
    client = MagicMock()
    bucket = MagicMock()
    blob = MagicMock()
    client.bucket.return_value = bucket
    bucket.blob.return_value = blob

    blob.upload_from_string.side_effect = g_exceptions.NotFound("Bucket not found 404")
    monkeypatch.setattr("time.sleep", lambda s: None)

    service = GCSStorageService(bucket_name="nonexistent-bucket", client=client)
    service.local_dir = tmp_path

    res = service.upload_json({"alert_id": "A999"}, execution_id="exec_fallback")

    assert res.success is True
    assert res.is_fallback is True
    assert res.local_path is not None
    assert tmp_path.exists()

    # Verify buffered file content
    with open(res.local_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data["alert_id"] == "A999"


def test_gcs_disabled_writes_directly_to_local_fallback(tmp_path):
    service = GCSStorageService(bucket_name="test-bucket")
    service.enabled = False
    service.local_dir = tmp_path

    res = service.upload_markdown("# Offline Mode", execution_id="exec_offline")
    assert res.success is True
    assert res.is_fallback is True
    assert "Offline Mode" in open(res.local_path, "r", encoding="utf-8").read()
