import pytest
from prompts import get_system_instruction, format_investigation_prompt


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
    assert "PLAYBOOK R1" in prompt


def test_specialized_playbooks():
    from agents.playbooks import get_playbook

    p1 = get_playbook("R1")
    assert p1.rule_id == "R1"
    assert "ADJUST_THRESHOLD" in p1.get_playbook_guidance()

    p2 = get_playbook("R2")
    assert p2.rule_id == "R2"
    assert "PAUSE_CAMPAIGN" in p2.get_playbook_guidance()

    p3 = get_playbook("R3")
    assert p3.rule_id == "R3"
    assert "TARGETING_OVERHAUL" in p3.get_playbook_guidance()
