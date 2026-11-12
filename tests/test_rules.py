import pytest
from domain.rules import generate_alert_id, get_rule_queries, parse_alert_row


def test_generate_alert_id_deterministic():
    id1 = generate_alert_id("R1", "CMP131")
    id2 = generate_alert_id("R1", "CMP131")
    assert id1 == id2
    assert id1.startswith("A")
    assert len(id1) == 5

    # Different rule or campaign produces different ID
    id3 = generate_alert_id("R2", "CMP131")
    assert id1 != id3


def test_rule_queries_contain_expected_filters():
    queries = get_rule_queries("test-project")
    assert "R1" in queries
    assert "R2" in queries
    assert "R3" in queries

    # R1 checks redemption_rate < 5.00
    assert "redemption_rate < 5.00" in queries["R1"]

    # R2 checks period decline
    assert "period_redemption_drop_pct" in queries["R2"]
    assert "p1_rate" in queries["R2"]
    assert "p2_rate" in queries["R2"]

    # R3 checks objective = 'ACQUIRE_NEW' and status = 'AWARDED'
    assert "ACQUIRE_NEW" in queries["R3"]
    assert "AWARDED" in queries["R3"]
    assert "existing_customer_share >= 75.00" in queries["R3"]


def test_parse_alert_row():
    row = {
        "campaign_id": "CMP131",
        "merchant_id": "M001",
        "rule_id": "R1",
        "metric_name": "redemption_rate",
        "metric_value": 4.0,
        "threshold": 5.0,
        "status": "OPEN",
    }
    alert = parse_alert_row(row)
    assert alert["campaign_id"] == "CMP131"
    assert alert["merchant_id"] == "M001"
    assert alert["rule_id"] == "R1"
    assert alert["metric_value"] == 4.0
    assert alert["threshold_value"] == 5.0
    assert alert["status"] == "OPEN"
    assert alert["alert_id"].startswith("A")
    assert "created_at" in alert
    assert "IST" in alert["created_at"]
