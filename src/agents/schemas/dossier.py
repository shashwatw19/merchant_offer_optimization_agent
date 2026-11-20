"""Structured Investigation Dossier output contract with resilient validators."""
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from core.time_utils import now_ist_str
from .evidence import EvidenceItem, normalize_source_and_id


class AlertPayload(BaseModel):
    alert_id: str
    campaign_id: str
    merchant_id: Optional[str] = None
    rule_id: Literal["R1", "R2", "R3"]
    metric_name: str
    metric_value: float
    threshold_value: float
    status: Literal["OPEN", "PROCESSING", "RESOLVED", "ERROR"] = "OPEN"
    created_at: str = Field(default_factory=now_ist_str)


class RecommendationAction(BaseModel):
    """Granular action item proposed by the optimization agent."""
    action_type: str = Field(
        default="MONITOR_VELOCITY",
        description="Operational category of this recommended action"
    )
    priority: str = Field(
        default="PRIMARY",
        description="Execution order and urgency of this recommendation"
    )
    parameter_changes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Concrete parameter modifications e.g. {'min_spend': 1500, 'cashback_cap': 200}"
    )
    expected_impact: str = Field(
        default="",
        description="Quantifiable business effect based on historical transaction replays"
    )
    risk_level: str = Field(
        default="LOW",
        description="Financial or merchant relationship risk level associated with this change"
    )
    rationale: str = Field(
        default="",
        description="Factual, evidence-based justification for this action"
    )

    @field_validator("action_type", mode="before")
    @classmethod
    def normalize_action_type(cls, v: Any) -> str:
        s = str(v).upper().strip().replace("-", "_").replace(" ", "_")
        if "TARGET" in s or "GEO" in s:
            return "TARGETING_OVERHAUL"
        if "THRESHOLD" in s or "SPEND" in s or "MIN" in s:
            return "ADJUST_THRESHOLD"
        if "PAUSE" in s or "STOP" in s or "HALT" in s:
            return "PAUSE_CAMPAIGN"
        if "EXTEND" in s or "RENEW" in s:
            return "EXTEND_CAMPAIGN"
        if "ESCALAT" in s or "RELATIONSHIP" in s or "MERCHANT" in s:
            return "MERCHANT_ESCALATION"
        if "MONITOR" in s or "VELOCITY" in s or "TRACK" in s:
            return "MONITOR_VELOCITY"
        return s or "MONITOR_VELOCITY"

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if "SECOND" in s:
            return "SECONDARY"
        if "CONTING" in s:
            return "CONTINGENCY"
        return "PRIMARY"

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if "HIGH" in s:
            return "HIGH"
        if "MED" in s:
            return "MEDIUM"
        return "LOW"


class Finding(BaseModel):
    observation: str
    evidence: List[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_finding_evidence(cls, v: Any) -> List[str]:
        if not v:
            return []
        if isinstance(v, (str, int, float)):
            return [str(v)]
        if isinstance(v, list):
            res = []
            for item in v:
                if isinstance(item, dict):
                    res.append(item.get("record_id") or item.get("source") or str(item))
                else:
                    res.append(str(item))
            return res
        return [str(v)]


class Hypothesis(BaseModel):
    text: str
    status: str = "UNVERIFIED"
    rationale: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_hypothesis_status(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if any(w in s for w in ("SUPPORT", "TRUE", "CONFIRM", "VALID", "PROV")):
            return "SUPPORTED"
        if any(w in s for w in ("REFUT", "FALSE", "REJECT", "DISPROV")):
            return "REFUTED"
        return "UNVERIFIED"


class ReplaySimulationResult(BaseModel):
    campaign_id: str
    current_min_spend: float
    proposed_min_spend: float
    budget: float
    current_qualifying_txns: int
    proposed_qualifying_txns: int
    additional_txns: int
    current_unique_customers: int
    proposed_unique_customers: int
    additional_customers: int
    current_cashback: float
    proposed_cashback: float
    additional_cashback: float
    budget_safe: bool
    status: str = "APPROVED_REPLAY"


class Proposal(BaseModel):
    type: str = "TEST"
    min_spend: Optional[float] = None
    cashback_pct: Optional[float] = None
    cashback_cap: Optional[float] = None
    rationale: Optional[str] = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_proposal_type(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if "KEEP" in s:
            return "KEEP"
        if "TEST" in s or "ADJUST" in s:
            return "TEST"
        if "MONITOR" in s:
            return "MONITOR"
        if "REJECT" in s:
            return "REJECT"
        return "INVESTIGATE"


class InvestigationDossier(BaseModel):
    """The enterprise JSON output schema for every investigated alert."""
    alert_id: str = Field(description="The alert investigated (e.g. 'ALT-202611-001')")
    campaign_id: str = Field(description="The underperforming campaign ID (e.g. 'CMP131')")
    merchant_id: Optional[str] = Field(default=None, description="The merchant associated with the campaign")
    execution_id: Optional[str] = Field(default=None, description="Unique execution correlation ID")
    generated_at: str = Field(default_factory=now_ist_str, description="Execution completion timestamp in IST")
    status: str = Field(default="COMPLETE", description="Investigation state")
    summary: str = Field(
        default="",
        description="2 to 3 plain English sentences explaining what happened and why this recommendation was reached"
    )
    recommendations: List[RecommendationAction] = Field(
        default_factory=list,
        description="List of structured, prioritized actions (array format)"
    )
    proposal: Optional[Proposal] = None
    findings: List[Finding] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(
        default_factory=list,
        description="List of cited records. Every claimed fact must have an entry"
    )
    red_flags: List[str] = Field(
        default_factory=list,
        description="Risk indicators found (e.g. outlet renovation, city mismatch, customer friction)"
    )
    simulation_result: Optional[ReplaySimulationResult] = None
    simulation_type: Optional[str] = "HISTORICAL_REPLAY"
    future_incremental_spend: Optional[float] = Field(
        default=None,
        description="Guardrail: Must remain null/None. Forward-looking revenue forecasting is strictly forbidden"
    )
    confidence: str = Field(default="HIGH", description="Agent's confidence in the supporting evidence")
    confidence_reason: str = Field(
        default="Evidence corroborated across silver transactions and merchant profiles.",
        description="Detailed rationale for the confidence score"
    )
    human_approval_required: bool = True
    metrics: Optional[Dict[str, Any]] = None
    campaign_terms: Optional[Dict[str, Any]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if "FAIL" in s or "ERR" in s:
            return "FAILED"
        if "INCONCLU" in s:
            return "INCONCLUSIVE"
        return "COMPLETE"

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_conf(cls, v: Any) -> str:
        s = str(v).upper().strip()
        if "LOW" in s:
            return "LOW"
        if "MED" in s:
            return "MEDIUM"
        return "HIGH"

    @field_validator("future_incremental_spend")
    @classmethod
    def enforce_null_forecast(cls, v):
        if v is not None:
            raise ValueError(
                "Guardrail Violation: future_incremental_spend must remain null. "
                "Predictive forecasting is forbidden; only historical replays are permitted."
            )
        return None

    @field_validator("evidence", mode="before")
    @classmethod
    def coerce_evidence_items(cls, v: Any) -> List[Any]:
        if not v:
            return []
        items = v if isinstance(v, list) else [v]
        res = []
        for item in items:
            if isinstance(item, EvidenceItem):
                res.append(item)
            elif isinstance(item, str):
                source, rec_id = normalize_source_and_id(item)
                res.append(EvidenceItem(source=source, record_id=rec_id or item, fact=f"Evidence: {item}"))
            elif isinstance(item, dict):
                res.append(item)
        return res

    @model_validator(mode="after")
    def populate_evidence_from_findings_if_empty(self) -> "InvestigationDossier":
        """If top-level evidence list is empty, backfill it from findings evidence citations."""
        if not self.evidence and self.findings:
            collected = []
            for f in self.findings:
                for ev_str in f.evidence:
                    source, rec_id = normalize_source_and_id(ev_str)
                    collected.append(
                        EvidenceItem(
                            source=source,
                            record_id=rec_id or ev_str,
                            fact=f.observation[:120] if f.observation else f"Evidence for {ev_str}"
                        )
                    )
            self.evidence = collected
        return self


# Alias InvestigationReport to InvestigationDossier
InvestigationReport = InvestigationDossier
