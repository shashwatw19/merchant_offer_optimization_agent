import hashlib
from pathlib import Path
from typing import Any, Dict
from core.config import get_config
from core.time_utils import now_ist_str

SQL_RULES_DIR = Path(__file__).resolve().parent.parent.parent / "sql" / "rules"


def generate_alert_id(rule_id: str, campaign_id: str) -> str:
    """Generate a stable, deterministic 5-character alert identifier."""
    raw = f"{rule_id}:{campaign_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    numeric = int(digest[:8], 16)
    return f"A{numeric % 9000 + 1000}"


def _load_sql_rule(filename: str, project: str, gold_dataset: str, silver_dataset: str) -> str:
    """Load and format a standalone rule SQL file from sql/rules/."""
    sql_path = SQL_RULES_DIR / filename
    if not sql_path.is_file():
        raise FileNotFoundError(f"Rule SQL file not found at: {sql_path}")
    with open(sql_path, "r", encoding="utf-8") as f:
        template = f.read()
    return template.format(
        project=project,
        gold_dataset=gold_dataset,
        silver_dataset=silver_dataset,
    )


def get_rule_queries(project_id: str = None) -> Dict[str, str]:
    """Return SQL queries for deterministic alert rules R1, R2, and R3 extracted from sql/rules/."""
    config = get_config()
    project = project_id or config.gcp.project_id
    gold_dataset = config.gcp.gold_dataset
    silver_dataset = config.gcp.silver_dataset

    return {
        "R1": _load_sql_rule("r1_low_redemption.sql", project, gold_dataset, silver_dataset),
        "R2": _load_sql_rule("r2_sudden_drop.sql", project, gold_dataset, silver_dataset),
        "R3": _load_sql_rule("r3_low_acquisition.sql", project, gold_dataset, silver_dataset),
    }


def parse_alert_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Construct an AlertPayload dictionary from a SQL result row."""
    rule_id = str(row["rule_id"])
    campaign_id = str(row["campaign_id"])
    raw_thresh = row.get("threshold_value") if "threshold_value" in row else row.get("threshold", 0.0)
    raw_metric = row.get("metric_value", 0.0)
    return {
        "alert_id": generate_alert_id(rule_id, campaign_id),
        "campaign_id": campaign_id,
        "merchant_id": row.get("merchant_id"),
        "rule_id": rule_id,
        "metric_name": row.get("metric_name", "unknown_metric"),
        "metric_value": float(raw_metric) if raw_metric is not None else 0.0,
        "threshold_value": float(raw_thresh) if raw_thresh is not None else 0.0,
        "status": row.get("status", "OPEN"),
        "created_at": str(row.get("created_at") or now_ist_str()),
    }
