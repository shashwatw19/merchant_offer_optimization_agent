"""Shim module for backward compatibility.

NOTE: report_tools has been refactored to src/services/report_converter.py.
Please import from services.report_converter in new code.
"""
from typing import Any, Dict, Optional
import services.report_converter as _report_converter
from services.gcs_storage import get_storage_service

def convert_json_report_to_markdown(*args, **kwargs) -> Dict[str, Any]:
    """Backward-compatible wrapper delegating to services.report_converter."""
    # Propagate any monkeypatched get_storage_service from this module to the converter
    orig_fn = getattr(_report_converter, "get_storage_service", None)
    try:
        _report_converter.get_storage_service = get_storage_service
        return _report_converter.convert_json_report_to_markdown(*args, **kwargs)
    finally:
        if orig_fn is not None:
            _report_converter.get_storage_service = orig_fn

__all__ = ["convert_json_report_to_markdown", "get_storage_service"]
