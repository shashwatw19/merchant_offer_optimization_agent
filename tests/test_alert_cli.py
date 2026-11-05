from unittest.mock import MagicMock
import pytest
import alert


def test_alert_cli_dry_run_collects_alerts(monkeypatch):
    mock_r1 = [{"campaign_id": "CMP131", "rule_id": "R1", "metric_value": 4.0, "threshold": 5.0}]
    mock_r2 = []
    mock_r3 = [{"campaign_id": "CMP133", "rule_id": "R3", "metric_value": 85.0, "threshold": 75.0}]

    def fake_execute(sql, parameters=None, client=None):
        if "redemption_rate < 5.00" in sql:
            return mock_r1
        elif "existing_customer_share >= 75.00" in sql:
            return mock_r3
        return []

    import core.bigquery_client as bq_mod
    monkeypatch.setattr(bq_mod, "execute_query", fake_execute)

    alerts = alert.run_all_alerts(project_id="test-proj")
    assert len(alerts) == 2
    rule_ids = {a["rule_id"] for a in alerts}
    assert "R1" in rule_ids
    assert "R3" in rule_ids


def test_alert_cli_single_rule_filter(monkeypatch):
    mock_r1 = [{"campaign_id": "CMP131", "rule_id": "R1", "metric_value": 4.0, "threshold": 5.0}]
    import core.bigquery_client as bq_mod
    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None, client=None: mock_r1)

    alerts = alert.run_all_alerts(project_id="test-proj", selected_rule="R1")
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "R1"
