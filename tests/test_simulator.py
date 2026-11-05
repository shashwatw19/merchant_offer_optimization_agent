import pytest
from domain.simulator import HistoricalReplaySimulator
from domain.policy import PolicyValidator
import core.bigquery_client as bq_client


def test_simulator_pre_validation_rejects_illegal_threshold():
    sim = HistoricalReplaySimulator()
    res = sim.simulate("CMP131", proposed_min_spend=500.0)
    assert res["success"] is False
    assert res["status"] == "REJECTED_BY_POLICY"
    assert "not in permitted thresholds" in res["error"]


def test_simulator_pre_validation_rejects_negative():
    sim = HistoricalReplaySimulator()
    res = sim.simulate("CMP131", proposed_min_spend=-1500.0)
    assert res["success"] is False
    assert res["status"] == "REJECTED_BY_POLICY"


def test_simulator_calculates_deltas_correctly(monkeypatch):
    mock_rows = [
        {
            "scenario": "current",
            "min_spend": 2000.0,
            "budget": 40000.0,
            "total_qualifying_txns": 6,
            "eligible_txns": 6,
            "unique_customers": 6,
            "simulated_cashback": 1200.0,
        },
        {
            "scenario": "proposed",
            "min_spend": 1500.0,
            "budget": 40000.0,
            "total_qualifying_txns": 18,
            "eligible_txns": 18,
            "unique_customers": 18,
            "simulated_cashback": 3600.0,
        },
    ]

    monkeypatch.setattr(bq_client, "execute_query", lambda sql, parameters=None, client=None: mock_rows)

    sim = HistoricalReplaySimulator()
    res = sim.simulate("CMP131", proposed_min_spend=1500.0)

    assert res["success"] is True
    assert res["status"] == "APPROVED_REPLAY"
    assert res["delta"]["additional_customers"] == 12
    assert res["delta"]["additional_txns"] == 12
    assert res["delta"]["additional_cashback"] == 2400.0
    assert res["budget_safe"] is True
    assert "disclaimer" in res
