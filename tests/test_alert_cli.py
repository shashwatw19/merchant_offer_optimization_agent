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
    assert "created_at" in alerts[0]
    assert "IST" in alerts[0]["created_at"]


def test_alert_cli_single_rule_filter(monkeypatch):
    mock_r1 = [{"campaign_id": "CMP131", "rule_id": "R1", "metric_value": 4.0, "threshold": 5.0}]
    import core.bigquery_client as bq_mod
    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None, client=None: mock_r1)

    alerts = alert.run_all_alerts(project_id="test-proj", selected_rule="R1")
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "R1"
    assert "IST" in alerts[0]["created_at"]


def test_alert_cli_suppresses_already_active_alert(monkeypatch):
    # Rule R1 triggers for CMP131 -> alert_id A8247
    mock_r1 = [{"campaign_id": "CMP131", "rule_id": "R1", "metric_value": 4.0, "threshold": 5.0}]
    # But BigQuery already reports A8247 is PROCESSING
    mock_existing_active = [{"alert_id": "A8247", "status": "PROCESSING", "resolved_at": None}]

    def fake_execute(sql, parameters=None, client=None):
        if "status IN ('OPEN', 'PROCESSING', 'RESOLVED')" in sql:
            return mock_existing_active
        elif "redemption_rate < 5.00" in sql:
            return mock_r1
        return []

    import core.bigquery_client as bq_mod
    monkeypatch.setattr(bq_mod, "execute_query", fake_execute)

    # With deduplication enabled (default)
    alerts = alert.run_all_alerts(project_id="test-proj", selected_rule="R1", filter_active=True)
    assert len(alerts) == 0  # A8247 was suppressed!

    # When deduplication is forced off
    forced_alerts = alert.run_all_alerts(project_id="test-proj", selected_rule="R1", filter_active=False)
    assert len(forced_alerts) == 1
    assert forced_alerts[0]["alert_id"] == "A8247"


def test_alert_cli_suppresses_recently_resolved_alert_in_cooldown(monkeypatch):
    mock_r1 = [{"campaign_id": "CMP131", "rule_id": "R1", "metric_value": 4.0, "threshold": 5.0}]
    from core.time_utils import now_ist_str
    # Alert was resolved 10 minutes ago
    mock_existing_resolved = [{"alert_id": "A8247", "status": "RESOLVED", "resolved_at": now_ist_str()}]

    def fake_execute(sql, parameters=None, client=None):
        if "status IN ('OPEN', 'PROCESSING', 'RESOLVED')" in sql:
            return mock_existing_resolved
        elif "redemption_rate < 5.00" in sql:
            return mock_r1
        return []

    import core.bigquery_client as bq_mod
    monkeypatch.setattr(bq_mod, "execute_query", fake_execute)

    alerts = alert.run_all_alerts(project_id="test-proj", selected_rule="R1", filter_active=True, cooldown_minutes=2.0)
    assert len(alerts) == 0  # In cooldown -> suppressed!
