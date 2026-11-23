import pytest
from prompts import (
    get_system_instruction,
    format_investigation_prompt,
    normalize_rule_id,
    get_playbook,
)


def test_get_system_instruction_default():
    instruction = get_system_instruction()
    assert "Principal Merchant Offer Optimization Agent" in instruction
    assert "OPERATING PRINCIPLES" in instruction
    assert "human_approval_required" in instruction
    # Master instruction contains all three domain playbooks
    assert "PLAYBOOK R1" in instruction
    assert "PLAYBOOK R2" in instruction
    assert "PLAYBOOK R3" in instruction


def test_get_system_instruction_specialized():
    # R1 instruction contains only R1 guidance
    instr_r1 = get_system_instruction("R1")
    assert "PLAYBOOK R1" in instr_r1
    assert "PLAYBOOK R2" not in instr_r1
    assert "PLAYBOOK R3" not in instr_r1

    # R2 instruction contains only R2 guidance
    instr_r2 = get_system_instruction("R2")
    assert "PLAYBOOK R2" in instr_r2
    assert "PLAYBOOK R1" not in instr_r2
    assert "PLAYBOOK R3" not in instr_r2

    # R3 instruction contains only R3 guidance
    instr_r3 = get_system_instruction("R3")
    assert "PLAYBOOK R3" in instr_r3
    assert "PLAYBOOK R1" not in instr_r3
    assert "PLAYBOOK R2" not in instr_r3


def test_normalize_rule_id():
    assert normalize_rule_id("R1") == "R1"
    assert normalize_rule_id("rule_1") == "R1"
    assert normalize_rule_id("RULE1") == "R1"
    assert normalize_rule_id("rule-1") == "R1"
    assert normalize_rule_id({"rule_id": "r2"}) == "R2"
    assert normalize_rule_id({"rule": "RULE_3"}) == "R3"
    assert normalize_rule_id(None) is None
    assert normalize_rule_id("DEFAULT") is None


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

    # Works with 'rule' key and aliases as well
    alert2 = {
        "alert_id": "A1002",
        "campaign_id": "CMP132",
        "rule": "RULE_2",
        "metric_value": 55.0,
    }
    prompt2 = format_investigation_prompt(alert2)
    assert "A1002" in prompt2
    assert "PLAYBOOK R2" in prompt2


def test_specialized_playbooks():
    p1 = get_playbook("R1")
    assert p1.rule_id == "R1"
    assert "ADJUST_THRESHOLD" in p1.get_playbook_guidance()
    assert "Branch B" in p1.get_playbook_guidance()
    assert "TARGETING_OVERHAUL" in p1.get_playbook_guidance()

    p2 = get_playbook("R2")
    assert p2.rule_id == "R2"
    assert "PAUSE_CAMPAIGN" in p2.get_playbook_guidance()
    assert "validate_proposal" in p2.get_playbook_guidance()
    assert "simulate_campaign_change" in p2.get_playbook_guidance()

    p3 = get_playbook("R3")
    assert p3.rule_id == "R3"
    assert "TARGETING_OVERHAUL" in p3.get_playbook_guidance()
    assert "validate_proposal" in p3.get_playbook_guidance()
    assert "simulate_campaign_change" in p3.get_playbook_guidance()

