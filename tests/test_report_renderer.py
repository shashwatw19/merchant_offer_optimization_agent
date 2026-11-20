import json
import pytest
from core.exceptions import ReportRenderingError
from domain.contracts import Finding, Hypothesis, InvestigationReport, Proposal
from services.report_renderer import ReportRendererService, render_report_to_markdown


@pytest.fixture
def sample_report_dict():
    return {
        "alert_id": "A1001",
        "campaign_id": "CMP131",
        "execution_id": "exec_A1001_20261111",
        "generated_at": "2026-11-11 10:00:00 UTC",
        "status": "COMPLETE",
        "summary": "Spice Route Kitchen campaign investigated for low redemption rate (4%).",
        "findings": [
            {
                "observation": "Audience redemption rate is 4.0%, below 5.0% threshold.",
                "evidence": ["bq:offers_gold.gold_campaign_results:CMP131"],
            },
            {
                "observation": "Median customer transaction amount is ₹750, whereas offer min_spend is ₹2000.",
                "evidence": ["bq:offers_gold.gold_merchant_spend_profile:M001"],
            },
        ],
        "hypotheses": [
            {
                "text": "The ₹2000 minimum spend creates significant barrier for diners whose average ticket is ₹750.",
                "status": "SUPPORTED",
                "rationale": "Historical replay confirms lowering spend to ₹1500 increases qualifying txns without budget overrun.",
            },
            {
                "text": "Communication delivery channel was degraded.",
                "status": "REFUTED",
                "rationale": "Delivery rate was 94%, within normal operational parameters.",
            },
            {
                "text": "Seasonal footfall decline.",
                "status": "UNVERIFIED",
                "rationale": "External merchant footfall index not yet available.",
            },
        ],
        "proposal": {
            "type": "TEST",
            "min_spend": 1500.0,
            "cashback_pct": 10.0,
            "cashback_cap": 200.0,
            "rationale": "Pilot ₹1500 spend threshold to align with dining bill distribution.",
        },
        "simulation_type": "HISTORICAL_REPLAY",
        "future_incremental_spend": None,
        "human_approval_required": True,
    }


def test_render_complete_report(sample_report_dict):
    md = render_report_to_markdown(sample_report_dict, execution_id="exec_test_001")
    assert "# Merchant Offer Investigation Report" in md
    assert "A1001" in md
    assert "CMP131" in md
    assert "exec_test_001" in md
    assert "COMPLETE" in md
    assert "Executive Summary" in md
    assert "Spice Route Kitchen" in md
    assert "4.0%, below 5.0%" in md
    assert "bq:offers_gold.gold_campaign_results:CMP131" in md
    assert "SUPPORTED" in md
    assert "REFUTED" in md
    assert "UNVERIFIED" in md
    assert "₹1,500.00" in md
    assert "10.00%" in md
    assert "₹200.00" in md
    assert "Human Approval Gate" in md
    assert "Predictive Revenue Guardrail" in md
    assert "Evidence Citations & Audit Provenance" in md


def test_render_from_pydantic_model():
    model = InvestigationReport(
        alert_id="A2002",
        campaign_id="CMP200",
        execution_id="exec_A2002",
        status="COMPLETE",
        summary="Audit summary.",
        findings=[Finding(observation="Test finding", evidence=["ref:table"])],
        hypotheses=[Hypothesis(text="Hyp 1", status="SUPPORTED", rationale="Evidence 1")],
        proposal=Proposal(type="MONITOR", min_spend=1000.0, cashback_pct=10.0, cashback_cap=200.0),
    )
    md = render_report_to_markdown(model)
    assert "A2002" in md
    assert "CMP200" in md
    assert "MONITOR" in md
    assert "₹1,000.00" in md


def test_render_from_json_string(sample_report_dict):
    json_str = json.dumps(sample_report_dict)
    service = ReportRendererService()
    md = service.render(json_str)
    assert "A1001" in md
    assert "Analysis & Key Findings" in md


def test_render_handles_missing_optional_fields():
    minimal_report = {
        "alert_id": "A3003",
        "campaign_id": "CMP300",
        "status": "INCONCLUSIVE",
    }
    md = render_report_to_markdown(minimal_report)
    assert "A3003" in md
    assert "CMP300" in md
    assert "INCONCLUSIVE" in md
    assert "No specific findings" in md
    assert "No diagnostic hypotheses" in md
    assert "No campaign parameter adjustments" in md


def test_render_invalid_input_raises_error():
    service = ReportRendererService()
    with pytest.raises(ReportRenderingError):
        service.render("not a json string {{{")

    with pytest.raises(ReportRenderingError):
        service.render(12345)  # Invalid type


def test_render_currency_and_pct_formatting():
    service = ReportRendererService()
    assert service._format_currency(2000) == "₹2,000.00"
    assert service._format_currency(1500.5) == "₹1,500.50"
    assert service._format_currency(None) == "N/A"
    assert service._format_pct(10.0) == "10.00%"
    assert service._format_pct(None) == "N/A"
