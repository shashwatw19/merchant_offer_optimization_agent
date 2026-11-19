"""Application services for Merchant Offer Optimization Agent."""
from services.alert_store import (
    ensure_alert_table,
    fetch_pending_alerts,
    update_alert_status,
)
from services.evidence_service import EvidenceResolver, get_evidence_resolver
from services.gcs_storage import GCSStorageService, get_storage_service
from services.report_converter import convert_json_report_to_markdown
from services.report_renderer import ReportRendererService, render_report_to_markdown
from services.run_store import (
    ensure_agent_runs_table,
    fetch_agent_runs,
    record_agent_run,
)

__all__ = [
    "ensure_alert_table",
    "fetch_pending_alerts",
    "update_alert_status",
    "ensure_agent_runs_table",
    "record_agent_run",
    "fetch_agent_runs",
    "EvidenceResolver",
    "get_evidence_resolver",
    "GCSStorageService",
    "get_storage_service",
    "ReportRendererService",
    "render_report_to_markdown",
    "convert_json_report_to_markdown",
]
