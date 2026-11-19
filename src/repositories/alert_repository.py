"""Shim module for backward compatibility.

NOTE: alert_repository has been consolidated under src/services/alert_store.py.
"""
from services.alert_store import (
    _get_alerts_columns,
    ensure_alert_table,
    fetch_pending_alerts,
    update_alert_status,
)

__all__ = [
    "_get_alerts_columns",
    "ensure_alert_table",
    "fetch_pending_alerts",
    "update_alert_status",
]
