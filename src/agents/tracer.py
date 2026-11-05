import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.logging import logger


class ExecutionTracer:
    """Records agent and tool execution traces to structured JSONL logs for auditing and evaluation."""

    def __init__(self, trace_dir: Optional[str] = None):
        self.trace_dir = Path(trace_dir or "logs/traces")
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def write_trace(
        self,
        alert_id: str,
        campaign_id: str,
        model: str,
        tool_calls: List[Dict[str, Any]],
        report: Optional[Dict[str, Any]],
        duration_ms: float,
        error: Optional[str] = None,
    ) -> Path:
        """Append an execution trace record to the daily JSONL trace log."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        trace_file = self.trace_dir / f"trace_{today}.jsonl"

        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alert_id": alert_id,
            "campaign_id": campaign_id,
            "model": model,
            "duration_ms": duration_ms,
            "tool_call_count": len(tool_calls),
            "tool_calls": tool_calls,
            "report": report,
            "error": error,
            "status": "FAILED" if error else "SUCCESS",
        }

        try:
            with open(trace_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
            logger.info(f"Recorded execution trace to {trace_file}", extra={"alert_id": alert_id})
        except Exception as exc:
            logger.error(f"Failed to record execution trace: {exc}")

        return trace_file
