import csv
from pathlib import Path
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


def test_rule_sql_files_reference_alert_rules_config():
    queries = get_rule_queries("test-project")
    for rule_id in ("R1", "R2", "R3"):
        assert "alert_rules_config" in queries[rule_id], f"Rule {rule_id} does not reference alert_rules_config"
        assert "test-project" in queries[rule_id]


def test_alert_rules_csv_seed_content():
    workspace_root = Path(__file__).resolve().parent.parent
    csv_path = workspace_root / "data" / "seeds" / "alert_rules.csv"
    assert csv_path.is_file(), f"Seed CSV not found at {csv_path}"

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))

    assert len(reader) >= 4
    rule_ids = {row["rule_id"] for row in reader}
    assert {"R1", "R2", "R3"}.issubset(rule_ids)

    # Verify R1 parameter
    r1_rows = [r for r in reader if r["rule_id"] == "R1"]
    assert r1_rows[0]["parameter"] == "redemption_rate_threshold"
    assert float(r1_rows[0]["value"]) == 5.0


def test_alert_rules_gold_ddl_exists():
    workspace_root = Path(__file__).resolve().parent.parent
    ddl_path = workspace_root / "sql" / "gold" / "alert_rules_config.sql"
    assert ddl_path.is_file()
    content = ddl_path.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE TABLE" in content
    assert "alert_rules_config" in content


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
    assert len(alert["created_at"]) == 19
    assert alert["created_at"][10] == " "

