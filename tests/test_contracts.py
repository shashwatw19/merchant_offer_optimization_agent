import pytest
from pydantic import ValidationError
from domain.contracts import InvestigationReport, Finding, Hypothesis, Proposal


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


def test_investigation_report_requires_mandatory_fields():
    with pytest.raises(ValidationError):
        # Missing alert_id and campaign_id
        InvestigationReport()
