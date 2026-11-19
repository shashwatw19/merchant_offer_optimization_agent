"""Investigation playbooks package."""
from agents.playbooks.base import BasePlaybook
from agents.playbooks.r1_threshold import PlaybookR1
from agents.playbooks.r2_drop import PlaybookR2
from agents.playbooks.r3_acquisition import PlaybookR3
from agents.playbooks.resolver import get_playbook

__all__ = [
    "BasePlaybook",
    "PlaybookR1",
    "PlaybookR2",
    "PlaybookR3",
    "get_playbook",
]
