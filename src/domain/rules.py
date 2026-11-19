import hashlib
from pathlib import Path
from typing import Any, Dict, Optional
from core.config import get_config
from core.time_utils import now_ist_str

_RULES_SQL_CACHE: Dict[str, str] = {}


def generate_alert_id(rule_id: str, campaign_id: str) -> str:
    """Generate a stable, deterministic 5-character alert identifier."""
    raw = f"{rule_id}:{campaign_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    numeric = int(digest[:8], 16)
    return f"A{numeric % 9000 + 1000}"


def _find_rules_sql_dir() -> Path:
    """Locate the sql/rules directory across workspace or package roots."""
    candidates = [
        Path.cwd() / "sql" / "rules",
        Path(__file__).resolve().parent.parent.parent / "sql" / "rules",
        Path(__file__).resolve().parent.parent / "sql" / "rules",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path("sql/rules")


def _load_rule_sql_template(filename: str) -> str:
    """Load and cache a rule SQL template from the sql/rules directory."""
    if filename in _RULES_SQL_CACHE:
        return _RULES_SQL_CACHE[filename]

    sql_path = _find_rules_sql_dir() / filename
    if sql_path.is_file():
        content = sql_path.read_text(encoding="utf-8")
        _RULES_SQL_CACHE[filename] = content
        return content

    raise FileNotFoundError(f"Rule SQL file not found: {sql_path}")


def get_rule_queries(project_id: Optional[str] = None) -> Dict[str, str]:
    """Return parameterized BigQuery SQL queries for deterministic alert rules R1, R2, and R3."""
    config = get_config()
    project = project_id or config.gcp.project_id
    gold_dataset = config.gcp.gold_dataset
    silver_dataset = config.gcp.silver_dataset

    context = {
        "project": project,
        "gold_dataset": gold_dataset,
        "silver_dataset": silver_dataset,
    }

    return {
        "R1": _load_rule_sql_template("r1_low_redemption.sql").format(**context),
        "R2": _load_rule_sql_template("r2_sudden_drop.sql").format(**context),
        "R3": _load_rule_sql_template("r3_low_acquisition.sql").format(**context),
    }


def parse_alert_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Construct an AlertPayload dictionary from a SQL result row."""
    rule_id = str(row["rule_id"])
    campaign_id = str(row["campaign_id"])
    return {
        "alert_id": generate_alert_id(rule_id, campaign_id),
        "campaign_id": campaign_id,
        "merchant_id": row.get("merchant_id"),
        "rule_id": rule_id,
        "metric_name": row.get("metric_name", "unknown_metric"),
        "metric_value": float(row["metric_value"]),
        "threshold_value": float(row["threshold"]),
        "status": row.get("status", "OPEN"),
        "created_at": str(row.get("created_at") or now_ist_str()),
    }
