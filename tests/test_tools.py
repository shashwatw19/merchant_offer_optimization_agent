import datetime
import decimal
import pytest
from core.bigquery_client import make_serializable
import core.bigquery_client as bq_client
from agents.tools.policy_tools import validate_proposal
import agents.tools.bigquery_tools as bq_tools


def test_make_serializable():
    data = {
        "amount": decimal.Decimal("1500.50"),
        "date": datetime.date(2026, 9, 15),
        "ts": datetime.datetime(2026, 9, 15, 12, 30, 0),
        "nested": [{"val": decimal.Decimal("10.0")}],
    }
    cleaned = make_serializable(data)
    assert cleaned["amount"] == 1500.50
    assert cleaned["date"] == "2026-09-15"
    assert "2026-09-15T12:30:00" in cleaned["ts"]
    assert cleaned["nested"][0]["val"] == 10.0


def test_validate_proposal_tool():
    res = validate_proposal(proposed_min_spend=1500, cashback_pct=10, cashback_cap=200)
    assert res["allowed"] is True

    res_invalid = validate_proposal(proposed_min_spend=999, cashback_pct=10, cashback_cap=200)
    assert res_invalid["allowed"] is False


def test_get_campaign_terms_tool(monkeypatch):
    mock_data = [{
        "campaign_id": "CMP131",
        "merchant_id": "M001",
        "objective": "ACQUIRE_NEW",
        "min_spend": 2000.0,
        "cashback_pct": 10.0,
        "cashback_cap": 200.0,
        "budget": 40000.0,
        "status": "ACTIVE",
    }]
    monkeypatch.setattr(bq_client, "execute_query", lambda sql, parameters=None, client=None: mock_data)

    res = bq_tools.get_campaign_terms("CMP131")
    assert res["success"] is True
    assert res["campaign_id"] == "CMP131"
    assert res["terms"]["min_spend"] == 2000.0
    assert "evidence_ref" in res


def test_get_delivery_metrics_tool(monkeypatch):
    mock_data = [{
        "campaign_id": "CMP131",
        "total_sends": 150,
        "targeted_customers": 150,
        "delivered_customers": 141,
        "failed_deliveries": 9,
        "delivery_rate_pct": 94.0,
        "out_of_city_customers": 12,
        "city_mismatch_pct": 8.0,
    }]
    monkeypatch.setattr(bq_client, "execute_query", lambda sql, parameters=None, client=None: mock_data)

    res = bq_tools.get_delivery_metrics("CMP131")
    assert res["success"] is True
    assert res["delivery_metrics"]["total_sends"] == 150
    assert res["delivery_metrics"]["delivered_customers"] == 141
    assert res["delivery_metrics"]["delivery_rate_pct"] == 94.0
    assert res["delivery_metrics"]["city_mismatch_pct"] == 8.0


def test_get_comparable_campaigns_tool(monkeypatch):
    mock_data = [
        {
            "campaign_id": "CMP201",
            "merchant_id": "M005",
            "merchant_name": "Royal Indian",
            "merchant_category": "restaurant",
            "merchant_city": "Pune",
            "min_spend": 1500.0,
            "cashback_pct": 10.0,
            "cashback_cap": 200.0,
            "redemption_rate": 8.5,
        }
    ]
    monkeypatch.setattr(bq_client, "execute_query", lambda sql, parameters=None, client=None: mock_data)

    res = bq_tools.get_comparable_campaigns("CMP131")
    assert res["success"] is True
    assert res["count"] == 1
    assert res["peer_campaigns"][0]["redemption_rate"] == 8.5
