"""Playbook resolver mapping rule_ids to specialized investigation playbooks."""
from typing import Any, Dict, Optional
from agents.playbooks.base import BasePlaybook
from agents.playbooks.r1_threshold import R1ThresholdPlaybook
from agents.playbooks.r2_drop import R2VelocityDropPlaybook
from agents.playbooks.r3_acquisition import R3AcquisitionPlaybook

_PLAYBOOKS: Dict[str, BasePlaybook] = {
    "R1": R1ThresholdPlaybook(),
    "R2": R2VelocityDropPlaybook(),
    "R3": R3AcquisitionPlaybook(),
}

_DEFAULT_PLAYBOOK = BasePlaybook()


def normalize_rule_id(rule_input: Any) -> Optional[str]:
    """Normalize rule identifiers from strings, dictionaries, or aliases into standard canonical IDs (R1, R2, R3)."""
    if rule_input is None:
        return None
    if isinstance(rule_input, dict):
        raw = rule_input.get("rule_id") or rule_input.get("rule")
    else:
        raw = str(rule_input)
    if not raw:
        return None

    clean = str(raw).upper().strip().replace("-", "_").replace(" ", "_")

    # Canonicalize known rule aliases
    if clean in ("R1", "RULE_1", "RULE1", "R_1", "LOW_REDEMPTION", "THRESHOLD"):
        return "R1"
    if clean in ("R2", "RULE_2", "RULE2", "R_2", "SUDDEN_DROP", "VELOCITY_DROP", "DROP"):
        return "R2"
    if clean in ("R3", "RULE_3", "RULE3", "R_3", "LOW_ACQUISITION", "ACQUISITION"):
        return "R3"

    if clean in _PLAYBOOKS:
        return clean

    return clean if clean != "DEFAULT" else None


def get_playbook(rule_id_or_alert: Any = None) -> BasePlaybook:
    """Resolve the appropriate playbook for a given rule_id or alert dictionary, defaulting to BasePlaybook."""
    canonical_id = normalize_rule_id(rule_id_or_alert)
    if not canonical_id:
        return _DEFAULT_PLAYBOOK
    return _PLAYBOOKS.get(canonical_id, _DEFAULT_PLAYBOOK)

