import os
from pathlib import Path
from typing import List, Optional
import yaml
from pydantic import BaseModel, Field


class AgentMetaConfig(BaseModel):
    name: str = "merchant_offer_optimization_agent"
    model: str = "gemini-3.5-flash"


class PolicyConfig(BaseModel):
    allowed_thresholds: List[float] = Field(default_factory=lambda: [1000.0, 1500.0, 2000.0])
    cashback_percent: float = 10.0
    cashback_cap: float = 200.0
    budget_ceiling: float = 40000.0


class InvestigationConfig(BaseModel):
    max_tool_calls: int = 10
    evidence_required: bool = True
    citations_required: bool = True


class GuardrailsConfig(BaseModel):
    read_only_tools: bool = True
    no_campaign_updates: bool = True
    no_customer_contact: bool = True
    no_future_uplift_predictions: bool = True


class ReportingConfig(BaseModel):
    include_findings: bool = True
    include_hypotheses: bool = True
    include_evidence_ids: bool = True
    include_recommendations: bool = True
    human_approval_required: bool = True


class GCPConfig(BaseModel):
    project_id: str = "prj-imp-act-campaign"
    location: str = "asia-south1"
    bronze_dataset: str = "offers_bronze"
    silver_dataset: str = "offers_silver"
    gold_dataset: str = "offers_gold"
    alerts_table: str = "offers_gold.alerts"


class AppConfig(BaseModel):
    agent: AgentMetaConfig = Field(default_factory=AgentMetaConfig)
    objective: str = (
        "Investigate campaign alerts and provide evidence-backed "
        "recommendations without modifying campaigns."
    )
    tools: List[str] = Field(
        default_factory=lambda: [
            "get_campaign_performance",
            "get_campaign_terms",
            "get_spend_distribution",
            "get_customer_reviews",
            "get_merchant_feedback",
            "get_delivery_metrics",
            "get_comparable_campaigns",
            "validate_proposal",
            "simulate_campaign_change",
        ]
    )
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    gcp: GCPConfig = Field(default_factory=GCPConfig)


_CONFIG_INSTANCE: Optional[AppConfig] = None


def find_campaign_yaml() -> Optional[Path]:
    """Search common candidate paths for campaign.yaml."""
    candidates = [
        Path.cwd() / "campaign.yaml",
        Path(__file__).resolve().parent.parent.parent / "campaign.yaml",
        Path(__file__).resolve().parent.parent / "campaign.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load configuration from YAML and apply environment overrides."""
    global _CONFIG_INSTANCE
    
    data = {}
    path = Path(config_path) if config_path else find_campaign_yaml()
    if path and path.is_file():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

    config = AppConfig(**data)

    # Environment variable overrides
    if "GCP_PROJECT" in os.environ:
        config.gcp.project_id = os.environ["GCP_PROJECT"]
    if "BQ_LOCATION" in os.environ:
        config.gcp.location = os.environ["BQ_LOCATION"]
    if "GEMINI_MODEL" in os.environ:
        config.agent.model = os.environ["GEMINI_MODEL"]

    _CONFIG_INSTANCE = config
    return config


def get_config() -> AppConfig:
    """Return the cached AppConfig instance, loading default if needed."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
