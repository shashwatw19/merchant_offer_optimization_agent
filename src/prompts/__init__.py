import json
from pathlib import Path
from typing import Any, Dict, Optional
from agents.playbooks.resolver import get_playbook

PROMPTS_DIR = Path(__file__).resolve().parent

_SYSTEM_INSTRUCTION_CACHE = None
_INVESTIGATION_PROMPT_CACHE = None


def get_system_instruction(rule_id: Optional[str] = None) -> str:
    """Load the system instruction prompt for a specific rule or master baseline."""
    if rule_id:
        return get_playbook(rule_id).build_system_instruction()

    global _SYSTEM_INSTRUCTION_CACHE
    if _SYSTEM_INSTRUCTION_CACHE is None:
        path = PROMPTS_DIR / "system_instruction.txt"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                _SYSTEM_INSTRUCTION_CACHE = f.read().strip()
        else:
            _SYSTEM_INSTRUCTION_CACHE = get_playbook().build_system_instruction()
    return _SYSTEM_INSTRUCTION_CACHE


def get_investigation_prompt_template() -> str:
    """Load the investigation user prompt template from disk or playbook default."""
    global _INVESTIGATION_PROMPT_CACHE
    if _INVESTIGATION_PROMPT_CACHE is None:
        path = PROMPTS_DIR / "investigation_prompt.txt"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                _INVESTIGATION_PROMPT_CACHE = f.read().strip()
        else:
            _INVESTIGATION_PROMPT_CACHE = get_playbook().build_investigation_prompt({"alert_json": "{alert_json}"})
    return _INVESTIGATION_PROMPT_CACHE


def format_investigation_prompt(alert: Dict[str, Any]) -> str:
    """Format the investigation prompt with the provided alert details using the matching Playbook."""
    rule_id = alert.get("rule_id")
    playbook = get_playbook(rule_id)
    return playbook.build_investigation_prompt(alert)
