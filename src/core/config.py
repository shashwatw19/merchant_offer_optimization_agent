import os
from pathlib import Path
from typing import Optional
import yaml


class ConfigDict(dict):
    """Dictionary allowing direct attribute access (e.g. config.policy.allowed_thresholds)."""

    def __getattr__(self, key):
        try:
            val = self[key]
            if isinstance(val, dict) and not isinstance(val, ConfigDict):
                val = ConfigDict(val)
                self[key] = val
            return val
        except KeyError:
            raise AttributeError(f"Attribute '{key}' not found in configuration")

    def __setattr__(self, key, value):
        self[key] = value


AppConfig = ConfigDict
_CONFIG_INSTANCE: Optional[ConfigDict] = None


def find_campaign_yaml() -> Path:
    """Find centralized campaign.yaml in config/ or workspace root."""
    candidates = [
        Path.cwd() / "config" / "campaign.yaml",
        Path.cwd() / "campaign.yaml",
        Path(__file__).resolve().parent.parent.parent / "config" / "campaign.yaml",
        Path(__file__).resolve().parent.parent.parent / "campaign.yaml",
        Path(__file__).resolve().parent.parent / "config" / "campaign.yaml",
        Path(__file__).resolve().parent.parent / "campaign.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return Path("config/campaign.yaml")


def load_config(config_path: Optional[str] = None) -> ConfigDict:
    """Load configuration directly without mutating global os.environ."""
    global _CONFIG_INSTANCE
    path = Path(config_path) if config_path else find_campaign_yaml()

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    config = ConfigDict(data)

    # Read environment variable overrides without mutating os.environ
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key and "agent" in config:
        config.agent["api_key"] = api_key

    proj_env = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if proj_env and "gcp" in config:
        config.gcp["project_id"] = proj_env

    loc_env = os.environ.get("GOOGLE_CLOUD_LOCATION") or os.environ.get("BQ_LOCATION")
    if loc_env and "gcp" in config:
        config.gcp["location"] = loc_env

    if "GEMINI_MODEL" in os.environ and "agent" in config:
        config.agent["model"] = os.environ["GEMINI_MODEL"]

    if "GCS_BUCKET" in os.environ and "storage" in config:
        config.storage["bucket_name"] = os.environ["GCS_BUCKET"]
    elif "GCS_REPORTS_BUCKET" in os.environ and "storage" in config:
        config.storage["bucket_name"] = os.environ["GCS_REPORTS_BUCKET"]

    if "GCS_STORAGE_ENABLED" in os.environ and "storage" in config:
        config.storage["enabled"] = os.environ["GCS_STORAGE_ENABLED"].lower() in ("true", "1", "yes")

    if "MAX_RETRY_COUNT" in os.environ:
        count = int(os.environ["MAX_RETRY_COUNT"])
        if "resilience" in config:
            config.resilience["max_retry_count"] = count
            config.resilience["retry_count"] = count
        if "investigation" in config:
            config.investigation["max_retry_count"] = count
            config.investigation["retry_count"] = count

    _CONFIG_INSTANCE = config
    return config


def get_config() -> ConfigDict:
    """Return the cached configuration instance."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None:
        _CONFIG_INSTANCE = load_config()
    return _CONFIG_INSTANCE
