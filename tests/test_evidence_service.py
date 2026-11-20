"""Unit tests for the Evidence Verification Service."""

from unittest.mock import patch
import pytest

from services.evidence_service import EvidenceResolver


@pytest.fixture
def resolver():
    return EvidenceResolver()


def test_resolve_rule_evidence(resolver):
    res = resolver.resolve_evidence("rule:R1", campaign_id="CMP131")
    assert res["success"] is True
    assert res["target_type"] == "RULE_DEFINITION"
    assert res["resolved_id"] == "R1"
    assert res["verification_verdict"] == "RULE_POLICY_EVALUATION"


def test_resolve_gold_results_evidence(resolver):
    mock_row = [{
        "campaign_id": "CMP131",
        "merchant_id": "M001",
        "redemption_rate_pct": 4.0,
        "cashback_amt_awarded": 1200.0,
    }]
    with patch("core.bigquery_client.execute_query", return_value=mock_row):
        res = resolver.resolve_evidence("bq:offers_gold.gold_campaign_results:CMP131", campaign_id="CMP131")
        assert res["success"] is True
        assert res["target_type"] == "GOLD_AGGREGATE"
        assert res["resolved_id"] == "CMP131"
        assert res["record_count"] == 1
        assert res["records"][0]["redemption_rate_pct"] == 4.0
        assert len(res["lineage"]) >= 3


def test_resolve_campaign_terms_evidence(resolver):
    mock_campaign = [{
        "campaign_id": "CMP131",
        "merchant_id": "M001",
        "objective": "ACQUIRE_NEW",
        "min_spend": "2000.00",
        "cashback_pct": "10.00",
        "batch_id": "BATCH_01",
        "ingestion_ts": "2026-11-11T05:00:00",
    }]
    with patch("core.bigquery_client.execute_query", return_value=mock_campaign):
        res = resolver.resolve_evidence("bq:offers_silver.campaigns:CMP131", campaign_id="CMP131")
        assert res["success"] is True
        assert res["target_type"] == "CAMPAIGN_TERMS"
        assert "campaigns_raw" in res["source_table"]
        assert res["resolved_id"] == "CMP131"
        assert res["records"][0]["min_spend"] == "2000.00"
        assert res["batch_id"] == "BATCH_01"


def test_resolve_customer_reviews_evidence(resolver):
    mock_reviews = [{
        "review_id": "REV108",
        "merchant_id": "M001",
        "rating": "2.0",
        "review_text": "Prices too high for the minimum order.",
        "batch_id": "BATCH_REV_01",
        "ingestion_ts": "2026-11-11T05:00:00",
    }]
    with patch("core.bigquery_client.execute_query", return_value=mock_reviews):
        res = resolver.resolve_evidence("review_id: REV108", merchant_id="M001")
        assert res["success"] is True
        assert res["target_type"] == "CUSTOMER_REVIEWS"
        assert "customer_reviews_raw" in res["source_table"]
        assert res["resolved_id"] == "REV108"
        assert res["record_count"] == 1


def test_resolve_merchant_feedback_evidence(resolver):
    mock_feedback = [{
        "feedback_id": "FB045",
        "merchant_id": "M001",
        "event_date": "2026-10-15",
        "feedback_text": "Kitchen renovation during mid-campaign.",
        "verification_status": "CONFIRMED",
        "batch_id": "BATCH_FB_01",
        "ingestion_ts": "2026-11-11T05:00:00",
    }]
    with patch("core.bigquery_client.execute_query", return_value=mock_feedback):
        res = resolver.resolve_evidence("feedback_id: FB045", merchant_id="M001")
        assert res["success"] is True
        assert res["target_type"] == "MERCHANT_FEEDBACK"
        assert "merchant_feedback_raw" in res["source_table"]
        assert res["resolved_id"] == "FB045"


def test_mask_sensitive_data(resolver):
    records = [{"customer_id": "C001", "card_number": "1234567812345678", "amount": 1500}]
    masked = resolver._mask_sensitive_data(records)
    assert masked[0]["customer_id"] == "C001"
    assert masked[0]["card_number"] == "****-****-****-5678"
    assert masked[0]["amount"] == 1500


def test_resolve_query_error_handling(resolver):
    with patch("core.bigquery_client.execute_query", side_effect=RuntimeError("BigQuery timeout")):
        res = resolver.resolve_evidence("bq:offers_silver.campaigns:CMP999", campaign_id="CMP999")
        assert res["success"] is False
        assert res["verification_verdict"] == "DATA_UNAVAILABLE"
        assert "BigQuery timeout" in res["error"]
