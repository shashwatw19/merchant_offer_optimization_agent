import pytest
from domain.policy import PolicyValidator


def test_policy_validator_allowed_proposals():
    validator = PolicyValidator()
    # 1000, 1500, 2000 are in the allowlist
    res_1000 = validator.validate_proposal(1000, 10, 200)
    assert res_1000["allowed"] is True

    res_1500 = validator.validate_proposal(1500, 10, 200)
    assert res_1500["allowed"] is True

    res_2000 = validator.validate_proposal(2000, 10, 200)
    assert res_2000["allowed"] is True


def test_policy_validator_disallowed_threshold():
    validator = PolicyValidator()
    # 500 and 1200 are not allowed
    res_500 = validator.validate_proposal(500, 10, 200)
    assert res_500["allowed"] is False
    assert "not in permitted thresholds" in res_500["reason"]

    res_1200 = validator.validate_proposal(1200, 10, 200)
    assert res_1200["allowed"] is False


def test_policy_validator_disallowed_cashback_pct():
    validator = PolicyValidator()
    res = validator.validate_proposal(1500, 15, 200)
    assert res["allowed"] is False
    assert "cashback_pct" in res["reason"]


def test_policy_validator_disallowed_cashback_cap():
    validator = PolicyValidator()
    res = validator.validate_proposal(1500, 10, 500)
    assert res["allowed"] is False
    assert "cashback_cap" in res["reason"]


def test_policy_validator_negative_values():
    validator = PolicyValidator()
    res = validator.validate_proposal(-1000, 10, 200)
    assert res["allowed"] is False
    assert "cannot be negative" in res["reason"]


def test_policy_validator_budget_ceiling():
    validator = PolicyValidator()
    res_ok = validator.validate_proposal(1500, 10, 200, budget=30000)
    assert res_ok["allowed"] is True

    res_over = validator.validate_proposal(1500, 10, 200, budget=50000)
    assert res_over["allowed"] is False
    assert "exceeds global budget ceiling" in res_over["reason"]


def test_policy_validator_invalid_types():
    validator = PolicyValidator()
    res = validator.validate_proposal("invalid", 10, 200)
    assert res["allowed"] is False
    assert "Invalid input types" in res["reason"]
