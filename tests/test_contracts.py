import pytest
from pydantic import ValidationError
from domain.contracts import AlertPayload, InvestigationReport, Finding, Hypothesis, Proposal


def test_investigation_report_valid_contract():
    report = InvestigationReport(
        alert_id="A1001",
        campaign_id="CMP131",
        findings=[
            Finding(observation="Redemption 4%", evidence=["bq:offers_gold.gold_campaign_results:CMP131"]),
            Finding(observation="Median merchant bill ₹750", evidence=["bq:offers_gold.gold_merchant_spend_profile:M001"]),
        ],
        hypotheses=[
            Hypothesis(text="Threshold of ₹2000 is restrictive", status="UNVERIFIED")
        ],
        proposal=Proposal(type="TEST", min_spend=1500, cashback_pct=10, cashback_cap=200),
        simulation_type="HISTORICAL_REPLAY",
        future_incremental_spend=None,
        human_approval_required=True,
    )
    dumped = report.model_dump()
    assert dumped["alert_id"] == "A1001"
    assert dumped["campaign_id"] == "CMP131"
    assert len(dumped["findings"]) == 2
    assert dumped["proposal"]["min_spend"] == 1500
    assert dumped["future_incremental_spend"] is None
    assert dumped["human_approval_required"] is True
    assert len(dumped["generated_at"]) == 19
    assert dumped["generated_at"][10] == " "


def test_alert_payload_created_at_in_ist():
    payload = AlertPayload(
        alert_id="A1001",
        campaign_id="CMP131",
        rule_id="R1",
        metric_name="redemption_rate",
        metric_value=4.0,
        threshold_value=5.0,
    )
    dumped = payload.model_dump()
    assert "created_at" in dumped
    assert len(dumped["created_at"]) == 19
    assert dumped["created_at"][10] == " "


def test_investigation_report_requires_mandatory_fields():
    with pytest.raises(ValidationError):
        # Missing alert_id and campaign_id
        InvestigationReport()
