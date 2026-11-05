import json
from pathlib import Path
from typing import Any, Dict

PROMPTS_DIR = Path(__file__).resolve().parent

_SYSTEM_INSTRUCTION_CACHE = None
_INVESTIGATION_PROMPT_CACHE = None


def get_system_instruction() -> str:
    """Load the master system instruction prompt from disk."""
    global _SYSTEM_INSTRUCTION_CACHE
    if _SYSTEM_INSTRUCTION_CACHE is None:
        path = PROMPTS_DIR / "system_instruction.txt"
        with open(path, "r", encoding="utf-8") as f:
            _SYSTEM_INSTRUCTION_CACHE = f.read().strip()
    return _SYSTEM_INSTRUCTION_CACHE


def get_investigation_prompt_template() -> str:
    """Load the investigation user prompt template from disk."""
    global _INVESTIGATION_PROMPT_CACHE
    if _INVESTIGATION_PROMPT_CACHE is None:
        path = PROMPTS_DIR / "investigation_prompt.txt"
        with open(path, "r", encoding="utf-8") as f:
            _INVESTIGATION_PROMPT_CACHE = f.read().strip()
    return _INVESTIGATION_PROMPT_CACHE


def format_investigation_prompt(alert: Dict[str, Any]) -> str:
    """Format the investigation prompt with the provided alert details."""
    template = get_investigation_prompt_template()
    alert_json = json.dumps(alert, indent=2, default=str)
    return template.replace("{alert_json}", alert_json)
