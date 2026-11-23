"""Prompts package providing programmatic prompt functions."""
from prompts.prompt_builder import (
    format_investigation_prompt,
    get_system_instruction,
    build_master_system_instruction,
)
from agents.playbooks.resolver import get_playbook, normalize_rule_id

__all__ = [
    "format_investigation_prompt",
    "get_system_instruction",
    "build_master_system_instruction",
    "get_playbook",
    "normalize_rule_id",
]
