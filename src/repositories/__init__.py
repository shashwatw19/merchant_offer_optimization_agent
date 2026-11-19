"""Data repositories package."""
from repositories.alert_repository import (
    ensure_alert_table,
    fetch_pending_alerts,
    update_alert_status,
)

__all__ = [
    "ensure_alert_table",
    "fetch_pending_alerts",
    "update_alert_status",
]
