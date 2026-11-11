from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class AlertPayload(BaseModel):
    alert_id: str
    campaign_id: str
    merchant_id: Optional[str] = None
    rule_id: Literal["R1", "R2", "R3"]
    metric_name: str
    metric_value: float
    threshold_value: float
    status: Literal["OPEN", "PROCESSING", "RESOLVED", "ERROR"] = "OPEN"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    )


class Finding(BaseModel):
    observation: str
    evidence: List[str] = Field(default_factory=list)


class Hypothesis(BaseModel):
    text: str
    status: Literal["UNVERIFIED", "SUPPORTED", "REFUTED"] = "UNVERIFIED"
    rationale: Optional[str] = None


class Proposal(BaseModel):
    type: Literal["KEEP", "TEST", "MONITOR", "INVESTIGATE", "REJECT"] = "TEST"
    min_spend: Optional[float] = None
    cashback_pct: Optional[float] = None
    cashback_cap: Optional[float] = None
    rationale: Optional[str] = None


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


class InvestigationReport(BaseModel):
    alert_id: str
    campaign_id: str
    execution_id: Optional[str] = None
    generated_at: Optional[str] = None
    status: Literal["COMPLETE", "INCONCLUSIVE", "FAILED"] = "COMPLETE"
    findings: List[Finding] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    proposal: Optional[Proposal] = None
    simulation_type: Optional[str] = "HISTORICAL_REPLAY"
    future_incremental_spend: Optional[float] = None  # Guardrail: Must remain null/None
    human_approval_required: bool = True
    summary: Optional[str] = None
