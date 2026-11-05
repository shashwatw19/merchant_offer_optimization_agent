import os
import pytest
from core.config import AppConfig, load_config, get_config


def test_load_config_defaults():
    config = get_config()
    assert config.agent.name == "merchant_offer_optimization_agent"
    assert config.policy.cashback_percent == 10.0
    assert config.policy.cashback_cap == 200.0
    assert config.policy.budget_ceiling == 40000.0
    assert 1000.0 in config.policy.allowed_thresholds
    assert 1500.0 in config.policy.allowed_thresholds
    assert 2000.0 in config.policy.allowed_thresholds
    assert config.investigation.max_tool_calls == 10
    assert config.guardrails.read_only_tools is True
    assert config.reporting.human_approval_required is True


def test_config_env_overrides(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "test-custom-project")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash-test")
    config = load_config()
    assert config.gcp.project_id == "test-custom-project"
    assert config.agent.model == "gemini-2.5-flash-test"
