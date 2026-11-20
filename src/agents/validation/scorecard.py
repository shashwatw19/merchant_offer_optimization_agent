"""Programmatic safety invariant enforcement."""
from core.logging import logger
from agents.schemas.dossier import InvestigationDossier, RecommendationAction

SEVERN_NEGATIVE_KEYWORDS = (
    "renovation", "closure", "closed", "mismatch", "outage", "collapse",
    "complaint", "negative", "drop", "cannibaliz", "friction"
)


def enforce_safety_override(dossier: InvestigationDossier) -> None:
    """Non-negotiable invariant: NEVER suggest passive KEEP/MONITOR when severe red flags exist."""
    has_red_flags = bool(dossier.red_flags)
    negative_observations = [
        f.observation for f in dossier.findings
        if any(kw in f.observation.lower() for kw in SEVERN_NEGATIVE_KEYWORDS)
    ]

    is_risky = has_red_flags or bool(negative_observations)
    if not is_risky:
        return

    # Check existing recommendations
    has_active_intervention = any(
        act.action_type in ("PAUSE_CAMPAIGN", "ADJUST_THRESHOLD", "TARGETING_OVERHAUL", "MERCHANT_ESCALATION")
        for act in dossier.recommendations
    )

    if not has_active_intervention:
        logger.warning(
            f"Safety Invariant Override: Alert {dossier.alert_id} has negative signals/red_flags but lacked active action. "
            f"Programmatically injecting MERCHANT_ESCALATION."
        )
        dossier.recommendations.insert(
            0,
            RecommendationAction(
                action_type="MERCHANT_ESCALATION",
                priority="PRIMARY",
                parameter_changes={},
                expected_impact="Escalates operational/targeting risk to relationship manager before deployment.",
                risk_level="HIGH",
                rationale="Programmatic Safety Override: Alert has unresolved red flags requiring operational intervention."
            )
        )
        if dossier.proposal and dossier.proposal.type in ("KEEP", "MONITOR"):
            dossier.proposal.type = "INVESTIGATE"
