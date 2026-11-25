from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import re

import pytest

from pipeline import (
    ENTITY_SPEC_MAP,
    ENTITY_SPECS,
    WatermarkService,
    match_entity_for_uri,
)
from pipeline.incremental_runner import (
    build_bronze_load_sql,
    run_bronze_incremental,
    run_silver_incremental,
)


class _FakeStorageClient:
    def __init__(self, blobs):
        self._blobs = blobs

    def list_blobs(self, bucket_name, prefix=""):
        return [b for b in self._blobs if b.name.startswith(prefix)]


def _make_blob(name, etag="etag-1", generation=100, size=256):
    return SimpleNamespace(
        name=name,
        etag=etag,
        md5_hash=etag,
        generation=generation,
        size=size,
        updated=datetime(2026, 11, 24, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_generate_batch_id_format():
    wm = WatermarkService(project_id="test-proj")
    batch_id = wm.generate_batch_id()
    assert re.match(r"^B_\d{6}_\d{4}$", batch_id)


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("raw_data/merchants.csv", "merchants"),
        ("raw_data/merchants_20261124.csv", "merchants"),
        ("raw_data/merchant_feedback_20261124.csv", "merchant_feedback"),
        ("raw_data/customer_reviews/delta_01.csv", "customer_reviews"),
        ("raw_data/customers_delta.csv", "customers"),
        ("raw_data/2026-11-24/campaigns.csv", "campaigns"),
        ("gs://bucket/raw_data/transactions_20261124_01.csv", "transactions"),
        ("raw_data/offer_sends_part1.csv", "offer_sends"),
        ("raw_data/offer_redemptions_batch2.csv", "offer_redemptions"),
        ("raw_data/transactions_20261124.parquet", None),
        ("raw_data/unknown_file.csv", None),
    ],
)
def test_match_entity_for_uri(uri, expected):
    assert match_entity_for_uri(uri) == expected


def test_discover_delta_files_filters_ingested(monkeypatch):
    import pipeline.watermark_service as wm_mod

    def fake_execute_query(sql, parameters=None, **kwargs):
        assert "gcs_ingestion_log" in sql
        return [
            {
                "file_uri": "gs://raw-bucket/raw_data/transactions_day1.csv",
                "file_etag": "etag-1",
                "gcs_generation_id": 100,
            }
        ]

    monkeypatch.setattr(wm_mod, "execute_query", fake_execute_query)

    blobs = [
        _make_blob("raw_data/transactions_day1.csv", etag="etag-1", generation=100),  # already ingested
        _make_blob("raw_data/transactions_day2.csv", etag="etag-2", generation=101),  # new delta
        _make_blob("raw_data/merchants_day2.csv", etag="etag-m1", generation=200),    # new dimension
    ]
    wm = WatermarkService(project_id="test-proj")
    discovered = wm.discover_delta_files(
        bucket_name="raw-bucket",
        prefix="raw_data/",
        storage_client=_FakeStorageClient(blobs),
    )

    assert len(discovered["transactions"]["skipped"]) == 1
    assert len(discovered["transactions"]["pending"]) == 1
    assert discovered["transactions"]["pending"][0]["file_name"] == "transactions_day2.csv"
    assert len(discovered["merchants"]["pending"]) == 1


def test_build_bronze_load_sql_applies_high_watermark_for_events():
    txn_spec = ENTITY_SPEC_MAP["transactions"]
    sql, params = build_bronze_load_sql(
        spec=txn_spec,
        delta_uris=["gs://b/raw_data/transactions_day2.csv"],
        project_id="test-proj",
        bronze_dataset="offers_bronze",
        high_watermark="2026-11-23T18:30:00+00:00",
        enforce_row_watermark=True,
    )
    assert "uris = ['gs://b/raw_data/transactions_day2.csv']" in sql
    assert "WHERE (" in sql
    assert "@high_watermark" in sql
    assert len(params) == 1
    assert params[0].name == "high_watermark"

    # Dimension tables should not get a row-level timestamp filter
    merch_spec = ENTITY_SPEC_MAP["merchants"]
    m_sql, m_params = build_bronze_load_sql(
        spec=merch_spec,
        delta_uris=["gs://b/raw_data/merchants_day2.csv"],
        project_id="test-proj",
        bronze_dataset="offers_bronze",
        high_watermark="2026-11-23T18:30:00+00:00",
        enforce_row_watermark=True,
    )
    assert "WHERE" not in m_sql
    assert m_params == []


def test_incremental_bronze_and_silver_commit_flow(monkeypatch):
    import pipeline.incremental_runner as runner_mod
    import pipeline.watermark_service as wm_mod

    executed_queries = []

    def fake_execute_query(sql, parameters=None, **kwargs):
        executed_queries.append((sql, parameters or []))
        if "FROM (" in sql and "gcs_ingestion_log" in sql:
            return []
        if "FROM `test-proj.offers_bronze.pipeline_watermark`" in sql and "SELECT" in sql:
            return [{"entity_name": "transactions", "high_watermark": "2026-11-23T10:00:00+00:00"}]
        if "discrepancy_count" in sql:
            return [
                {
                    "bronze_rows": 15,
                    "silver_rows": 14,
                    "rejected_rows": 1,
                    "discrepancy_count": 0,
                    "max_source_ts": "2026-11-24T11:30:00+00:00",
                }
            ]
        if "SELECT COUNT(*) AS cnt" in sql:
            return [{"cnt": 15}]
        return []

    monkeypatch.setattr(wm_mod, "execute_query", fake_execute_query)
    monkeypatch.setattr(runner_mod, "execute_query", fake_execute_query)

    blobs = [_make_blob("raw_data/transactions_20261124.csv", etag="e-new", generation=55)]
    wm = WatermarkService(project_id="test-proj")

    bronze_res = run_bronze_incremental(
        batch_id="B_261124_2330",
        entities=["merchants", "transactions"],
        watermark_service=wm,
        storage_client=_FakeStorageClient(blobs),
    )

    by_entity_b = {r["entity"]: r for r in bronze_res}
    assert by_entity_b["merchants"]["status"] == "SKIPPED"
    assert by_entity_b["transactions"]["status"] == "LOADED"
    assert by_entity_b["transactions"]["rows"] == 15

    silver_res = run_silver_incremental(
        batch_id="B_261124_2330",
        entities=["transactions"],
        watermark_service=wm,
    )
    assert silver_res[0]["status"] == "COMMITTED"
    assert silver_res[0]["discrepancy_count"] == 0

    merge_calls = [q for q, _ in executed_queries if "MERGE `test-proj.offers_bronze.pipeline_watermark`" in q]
    ingested_calls = [
        (q, p)
        for q, p in executed_queries
        if "UPDATE `test-proj.offers_bronze.gcs_ingestion_log`" in q
        and any(param.name == "status" and param.value == "INGESTED" for param in p)
    ]
    assert len(merge_calls) == 1
    assert len(ingested_calls) == 1


def test_silver_failure_does_not_advance_watermark(monkeypatch):
    import pipeline.incremental_runner as runner_mod
    import pipeline.watermark_service as wm_mod

    executed_queries = []

    def fake_execute_query(sql, parameters=None, **kwargs):
        executed_queries.append((sql, parameters or []))
        if "SELECT COUNT(*) AS cnt" in sql:
            return [{"cnt": 5}]
        if "CREATE OR REPLACE TEMP TABLE _stg_transactions" in sql:
            raise RuntimeError("Simulated BigQuery Silver error")
        return []

    monkeypatch.setattr(wm_mod, "execute_query", fake_execute_query)
    monkeypatch.setattr(runner_mod, "execute_query", fake_execute_query)

    wm = WatermarkService(project_id="test-proj")
    with pytest.raises(RuntimeError, match="Simulated BigQuery Silver error"):
        run_silver_incremental(
            batch_id="B_261124_2331",
            entities=["transactions"],
            watermark_service=wm,
        )

    watermark_merges = [q for q, _ in executed_queries if "MERGE `test-proj.offers_bronze.pipeline_watermark`" in q]
    failed_logs = [
        (q, p)
        for q, p in executed_queries
        if "UPDATE `test-proj.offers_bronze.gcs_ingestion_log`" in q
        and any(param.name == "status" and param.value == "FAILED" for param in p)
    ]
    assert watermark_merges == []
    assert len(failed_logs) == 1


def test_all_silver_sql_files_filter_by_batch_id():
    repo_root = Path(__file__).resolve().parent.parent
    for spec in ENTITY_SPECS:
        sql_path = repo_root / spec.silver_sql
        content = sql_path.read_text(encoding="utf-8")
        assert "r.batch_id = @batch_id" in content, f"{spec.silver_sql} missing r.batch_id = @batch_id filter"
