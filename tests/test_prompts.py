import pytest
from prompts import get_system_instruction, get_investigation_prompt_template, format_investigation_prompt


def test_get_system_instruction():
    instruction = get_system_instruction()
    assert "Principal Merchant Offer Optimization Agent" in instruction
    assert "OPERATING PRINCIPLES" in instruction
    assert "human_approval_required" in instruction


def test_format_investigation_prompt():
    alert = {
        "alert_id": "A1001",
        "campaign_id": "CMP131",
        "rule_id": "R1",
        "metric_value": 4.0,
    }
    prompt = format_investigation_prompt(alert)
    assert "A1001" in prompt
    assert "CMP131" in prompt
    assert "INVESTIGATION MANDATE" in prompt
