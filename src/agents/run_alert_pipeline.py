"""Backward-compatibility shim for renamed run_alert_investigation_pipeline module."""

from agents.run_alert_investigation_pipeline import (
    process_alert_batch,
    main,
)

__all__ = ["process_alert_batch", "main"]

if __name__ == "__main__":
    main()
