import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict as PydanticConfigDict
import yaml


class BaseConfigModel(BaseModel):
    model_config = PydanticConfigDict(extra="allow", arbitrary_types_allowed=True)

    def __getitem__(self, item: str) -> Any:
        try:
            return getattr(self, item)
        except AttributeError:
            raise KeyError(item)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def __contains__(self, item: str) -> bool:
        return hasattr(self, item) or item in self.__dict__

    def get(self, item: str, default: Any = None) -> Any:
        return getattr(self, item, default)


class AgentConfig(BaseConfigModel):
    name: str = "merchant_offer_optimization_agent"
    model: str = "gemini-3.5-flash"


class PolicyConfig(BaseConfigModel):
    allowed_thresholds: List[float] = Field(default_factory=lambda: [1000.0, 1250.0, 1500.0, 1750.0, 2000.0])
    cashback_percent: float = 10.0
    cashback_cap: float = 200.0
    budget_ceiling: float = 40000.0


class InvestigationConfig(BaseConfigModel):
    max_tool_calls: int = 9
    retry_count: int = 2
    max_retry_count: int = 2
    evidence_required: bool = True
    citations_required: bool = True
    alert_cooldown_minutes: float = 2.0


class ResilienceConfig(BaseConfigModel):
    retry_count: int = 2
    max_retry_count: int = 2
    backoff_min_sec: float = 0.5
    backoff_max_sec: float = 2.0
    timeout_sec: float = 15.0


class GCPConfig(BaseConfigModel):
    project_id: str = "prj-imp-act-campaign"
    location: str = "asia-south1"
    bronze_dataset: str = "offers_bronze"
    silver_dataset: str = "offers_silver"
    gold_dataset: str = "offers_gold"
    alerts_table: str = "offers_gold.alerts"


class GuardrailsConfig(BaseConfigModel):
    read_only_tools: bool = True
    no_campaign_updates: bool = True
    no_customer_contact: bool = True
    no_future_uplift_predictions: bool = True


class ReportingConfig(BaseConfigModel):
    include_findings: bool = True
    include_hypotheses: bool = True
    include_evidence_ids: bool = True
    include_recommendations: bool = True
    human_approval_required: bool = True


class StorageConfig(BaseConfigModel):
    enabled: bool = True
    provider: str = "gcs"
    bucket_name: str = "prj-imp-act-campaign-data"
    reports_prefix: str = "reports"
    local_fallback_dir: str = "output"
    timeout_sec: float = 15.0
    retry_count: int = 3


class AppConfig(BaseConfigModel):
    agent: AgentConfig = Field(default_factory=AgentConfig)
    objective: Optional[str] = None
    tools: List[str] = Field(default_factory=list)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    investigation: InvestigationConfig = Field(default_factory=InvestigationConfig)
    resilience: ResilienceConfig = Field(default_factory=ResilienceConfig)
    gcp: GCPConfig = Field(default_factory=GCPConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)


ConfigDict = AppConfig
_CONFIG_INSTANCE: Optional[AppConfig] = None


def find_campaign_yaml() -> Path:
    """Find campaign.yaml in workspace root."""
    candidates = [
        Path.cwd() / "campaign.yaml",
        Path(__file__).resolve().parent.parent.parent / "campaign.yaml",
        Path(__file__).resolve().parent.parent / "campaign.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path("campaign.yaml")


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Load and validate campaign.yaml into strongly typed Pydantic AppConfig."""
    global _CONFIG_INSTANCE
    path = Path(config_path) if config_path else find_campaign_yaml()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = AppConfig.model_validate(data)

    # Environment variable overrides & Google SDK synchronization
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["GOOGLE_API_KEY"] = api_key
    else:
        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")

    proj_env = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if proj_env:
        config.gcp.project_id = proj_env
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", config.gcp.project_id)
    os.environ.setdefault("GCP_PROJECT", config.gcp.project_id)

    loc_env = os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("BQ_LOCATION")
    if loc_env:
        config.gcp.location = loc_env
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", config.gcp.location)

    if "GEMINI_MODEL" in os.environ:
        config.agent.model = os.environ["GEMINI_MODEL"]

    if "GCS_BUCKET" in os.environ:
        config.storage.bucket_name = os.environ["GCS_BUCKET"]
    elif "GCS_REPORTS_BUCKET" in os.environ:
        config.storage.bucket_name = os.environ["GCS_REPORTS_BUCKET"]

    if "GCS_STORAGE_ENABLED" in os.environ:
        config.storage.enabled = os.environ["GCS_STORAGE_ENABLED"].lower() in ("true", "1", "yes")

    if "MAX_RETRY_COUNT" in os.environ:
        count = int(os.environ["MAX_RETRY_COUNT"])
        config.resilience.max_retry_count = count
        config.resilience.retry_count = count
        config.investigation.max_retry_count = count
        config.investigation.retry_count = count

    _CONFIG_INSTANCE = config
    return config


def get_config() -> AppConfig:
    """Return the cached validated AppConfig."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
