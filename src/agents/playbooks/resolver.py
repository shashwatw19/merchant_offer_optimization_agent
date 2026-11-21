"""Playbook resolver mapping rule_ids to specialized investigation playbooks."""
from typing import Optional
from agents.playbooks.base import BasePlaybook
from agents.playbooks.r1_threshold import R1ThresholdPlaybook
from agents.playbooks.r2_drop import R2VelocityDropPlaybook
from agents.playbooks.r3_acquisition import R3AcquisitionPlaybook

_PLAYBOOKS = {
    "R1": R1ThresholdPlaybook(),
    "R2": R2VelocityDropPlaybook(),
    "R3": R3AcquisitionPlaybook(),
}

_DEFAULT_PLAYBOOK = BasePlaybook()


def get_playbook(rule_id: Optional[str] = None) -> BasePlaybook:
    """Resolve the appropriate playbook for a given rule_id, defaulting to BasePlaybook."""
    if not rule_id:
        return _DEFAULT_PLAYBOOK
    clean_id = str(rule_id).upper().strip()
    return _PLAYBOOKS.get(clean_id, _DEFAULT_PLAYBOOK)
