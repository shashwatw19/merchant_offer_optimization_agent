"""Playbooks package for specialized rule investigations."""
from agents.playbooks.base import BasePlaybook
from agents.playbooks.r1_threshold import R1ThresholdPlaybook
from agents.playbooks.r2_drop import R2VelocityDropPlaybook
from agents.playbooks.r3_acquisition import R3AcquisitionPlaybook
from agents.playbooks.resolver import get_playbook

__all__ = [
    "BasePlaybook",
    "R1ThresholdPlaybook",
    "R2VelocityDropPlaybook",
    "R3AcquisitionPlaybook",
    "get_playbook",
]
