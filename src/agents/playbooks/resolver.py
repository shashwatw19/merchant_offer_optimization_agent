from typing import Optional
from agents.playbooks.base import BasePlaybook
from agents.playbooks.r1_threshold import PlaybookR1
from agents.playbooks.r2_drop import PlaybookR2
from agents.playbooks.r3_acquisition import PlaybookR3

_PLAYBOOKS = {
    "R1": PlaybookR1(),
    "R2": PlaybookR2(),
    "R3": PlaybookR3(),
}
_DEFAULT_PLAYBOOK = BasePlaybook()


def get_playbook(rule_id: Optional[str] = None) -> BasePlaybook:
    """Return the specialized Playbook for the given alert rule ID, or default baseline playbook."""
    if not rule_id:
        return _DEFAULT_PLAYBOOK
    clean_id = rule_id.strip().upper()
    return _PLAYBOOKS.get(clean_id, _DEFAULT_PLAYBOOK)
