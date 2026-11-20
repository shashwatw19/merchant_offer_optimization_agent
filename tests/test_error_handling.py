import pytest
from core.exceptions import DatabaseError
import core.bigquery_client as bq_mod
import agents.tools.bigquery_tools as bq_tools


def test_tool_handles_database_error_gracefully(monkeypatch):
    def failing_query(sql, parameters=None, client=None, timeout_sec=30.0):
        raise DatabaseError("BigQuery 503 Backend Unavailable", retryable=True)

    monkeypatch.setattr(bq_mod, "execute_query", failing_query)

    res_terms = bq_tools.get_campaign_terms("CMP131")
    assert res_terms["success"] is False
    assert "Failed retrieving campaign terms" in res_terms["error"]

    res_perf = bq_tools.get_campaign_performance("CMP131")
    assert res_perf["success"] is False
    assert "Failed retrieving campaign performance" in res_perf["error"]

    res_spend = bq_tools.get_spend_distribution("M001")
    assert res_spend["success"] is False
    assert "Failed retrieving spend distribution" in res_spend["error"]

    res_delivery = bq_tools.get_delivery_metrics("CMP131")
    assert res_delivery["success"] is False
    assert "Failed retrieving delivery metrics" in res_delivery["error"]


def test_simulate_handles_nonexistent_campaign(monkeypatch):
    monkeypatch.setattr(bq_mod, "execute_query", lambda sql, parameters=None, client=None: [])

    from domain.simulator import HistoricalReplaySimulator
    sim = HistoricalReplaySimulator()
    res = sim.simulate("CMP_NONEXISTENT", proposed_min_spend=1500.0)
    assert res["success"] is False
    assert "not found or transaction data missing" in res["error"]
