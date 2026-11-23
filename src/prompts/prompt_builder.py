"""Python prompt builder functions generating system instructions and investigation prompts."""
from typing import Any, Dict, Optional
from agents.playbooks.resolver import get_playbook, normalize_rule_id, _PLAYBOOKS
from agents.playbooks.base import (
    BASE_ROLE_DESCRIPTION,
    BASE_OPERATING_PRINCIPLES,
    BASE_INVESTIGATION_METHODOLOGY,
    BASE_OUTPUT_CONTRACT,
)
from agents.playbooks.r1_threshold import R1ThresholdPlaybook
from agents.playbooks.r2_drop import R2VelocityDropPlaybook
from agents.playbooks.r3_acquisition import R3AcquisitionPlaybook


def build_master_system_instruction() -> str:
    """Build the comprehensive enterprise system instruction containing all domain playbooks."""
    r1_guidance = R1ThresholdPlaybook().get_playbook_guidance()
    r2_guidance = R2VelocityDropPlaybook().get_playbook_guidance()
    r3_guidance = R3AcquisitionPlaybook().get_playbook_guidance()

    sections = [
        BASE_ROLE_DESCRIPTION,
        BASE_OPERATING_PRINCIPLES,
        BASE_INVESTIGATION_METHODOLOGY,
        BASE_OUTPUT_CONTRACT,
        f"DOMAIN INVESTIGATION PLAYBOOKS:\n\n{r1_guidance}\n\n{r2_guidance}\n\n{r3_guidance}",
    ]
    return "\n\n".join(sections).strip()


def get_system_instruction(rule_id: Optional[str] = None) -> str:
    """Return the system instruction prompt. If rule_id is provided and maps to a specialized playbook, returns rule-specialized instruction."""
    canonical_id = normalize_rule_id(rule_id)
    if canonical_id and canonical_id in _PLAYBOOKS:
        return get_playbook(canonical_id).build_system_instruction()
    return build_master_system_instruction()


def format_investigation_prompt(alert: Dict[str, Any]) -> str:
    """Format the investigation prompt with the provided alert details using the specialized playbook."""
    playbook = get_playbook(alert)
    return playbook.build_investigation_prompt(alert)
