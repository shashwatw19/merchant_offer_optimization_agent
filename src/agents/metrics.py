"""Invocation-local execution timing and provider-reported model usage."""

import asyncio
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional
from uuid import uuid4

try:
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext
except ImportError:
    CallbackContext = Any  # type: ignore
    LlmRequest = Any  # type: ignore
    LlmResponse = Any  # type: ignore
    BaseTool = Any  # type: ignore
    ToolContext = Any  # type: ignore

TOKEN_FIELDS = {
    "input_tokens": "prompt_token_count",
    "output_tokens": "candidates_token_count",
    "reasoning_tokens": "thoughts_token_count",
    "cached_input_tokens": "cached_content_token_count",
    "tool_prompt_tokens": "tool_use_prompt_token_count",
    "total_tokens": "total_token_count",
}

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(IST).isoformat()


def tool_response_failed(response: Any) -> bool:
    if isinstance(response, dict):
        if response.get("error"):
            return True
        if response.get("success") is False:
            return True
        return tool_response_failed(response.get("result"))
    if isinstance(response, list):
        return any(tool_response_failed(item) for item in response)
    return False


class InvestigationMetrics:
    def __init__(self) -> None:
        self.run_id = str(uuid4())
        self.started_at = _now()
        self._start = perf_counter()
        self.ended_at: Optional[str] = None
        self.duration_ms: Optional[float] = None
        self.agent_duration_ms: Optional[float] = None
        self.status = "running"
        self.error: Optional[str] = None
        self.attempt = 0
        self.model_name: Optional[str] = None
        self.model_calls: List[Dict[str, Any]] = []
        self.tool_calls: List[Dict[str, Any]] = []
        self._tool_records: Dict[tuple, Dict[str, Any]] = {}
        self._tool_starts: Dict[tuple, float] = {}
        self._model_start: Optional[float] = None
        self._usage_gap = False

    def request_tool(
        self,
        call_id: str,
        name: str,
        args: Dict[str, Any],
        step: int = 0,
        source: str = "model",
    ) -> Dict[str, Any]:
        key = (self.attempt, call_id)
        if key not in self._tool_records:
            row = {
                "tool_call_id": call_id,
                "model_call_id": self.model_calls[-1]["model_call_id"]
                if source == "model" and self.model_calls else None,
                "attempt": self.attempt,
                "step": step,
                "tool": name,
                "input": args,
                "source": source,
                "status": "requested",
                "started_at": None,
                "ended_at": None,
                "duration_ms": None,
                "direct_model_tokens": 0,
            }
            self._tool_records[key] = row
            self.tool_calls.append(row)
        return self._tool_records[key]

    def start_tool(
        self,
        call_id: str,
        name: str,
        args: Dict[str, Any],
        source: str = "model",
    ) -> None:
        row = self.request_tool(call_id, name, args, source=source)
        row.update(started_at=_now(), status="running")
        self._tool_starts[(self.attempt, call_id)] = perf_counter()

    def end_tool(
        self,
        call_id: str,
        result: Any = None,
        error: Optional[BaseException] = None,
        duration_ms: Optional[float] = None,
    ) -> None:
        key = (self.attempt, call_id)
        if key in self._tool_records:
            row = self._tool_records[key]
            start = self._tool_starts.pop(key, None)
            dur = duration_ms if duration_ms is not None else (
                round((perf_counter() - start) * 1000, 3) if start is not None else None
            )
            row.update(
                ended_at=_now(),
                duration_ms=dur,
                status="cancelled" if isinstance(error, asyncio.CancelledError)
                else "error" if error is not None or tool_response_failed(result) else "success",
            )
            if error is not None:
                row["error"] = str(error) or type(error).__name__
            else:
                row["output"] = result

    def tool_response(self, call_id: str, result: Any, duration_ms: Optional[float] = None) -> None:
        key = (self.attempt, call_id)
        row = self._tool_records.get(key)
        if row is not None:
            row["output"] = result
            if duration_ms is not None:
                row["duration_ms"] = duration_ms
            if tool_response_failed(result):
                row["status"] = "error"
            elif row.get("status") in ("requested", "running"):
                row["status"] = "success"

    def start_model(self) -> None:
        self._model_start = perf_counter()
        self.model_calls.append({
            "model_call_id": str(uuid4()),
            "model": self.model_name,
            "attempt": self.attempt,
            "started_at": _now(),
            "ended_at": None,
            "duration_ms": None,
            "status": "running",
            "usage": None,
        })

    def end_model(
        self,
        response: Optional[Any] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        if response is not None and getattr(response, "partial", False):
            return
        if not self.model_calls or self.model_calls[-1]["status"] != "running":
            return
        row = self.model_calls[-1]
        start = self._model_start
        dur = round((perf_counter() - start) * 1000, 3) if start is not None else None
        row.update(
            ended_at=_now(),
            duration_ms=dur,
            status="error" if error is not None or getattr(response, "error_code", None) else "success",
        )
        if error is not None:
            row["error"] = str(error) or type(error).__name__
        if response is not None:
            row["model"] = getattr(response, "model_version", None) or self.model_name
            usage_meta = getattr(response, "usage_metadata", None)
            if usage_meta is not None:
                if hasattr(usage_meta, "model_dump"):
                    row["usage"] = usage_meta.model_dump(mode="json", exclude_none=True)
                elif isinstance(usage_meta, dict):
                    row["usage"] = usage_meta
            row["cache_creation_input_tokens"] = getattr(response, "cache_creation_token_count", None)
            if getattr(response, "error_code", None):
                row["error"] = getattr(response, "error_message", None) or response.error_code

    def record_model_call(
        self,
        model: Optional[str] = None,
        duration_ms: Optional[float] = None,
        usage: Optional[Dict[str, Any]] = None,
        status: str = "success",
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience method to register a model call record directly."""
        call_id = str(uuid4())
        record = {
            "model_call_id": call_id,
            "model": model or self.model_name,
            "attempt": self.attempt,
            "started_at": _now(),
            "ended_at": _now(),
            "duration_ms": duration_ms,
            "status": status,
            "usage": usage,
            "error": error,
        }
        self.model_calls.append(record)
        return record

    def attempt_failed(self, error: BaseException) -> None:
        self._usage_gap = True
        self.end_model(error=error)
        self.close_tools("interrupted")

    def close_tools(self, status: str) -> None:
        for key in list(self._tool_starts):
            row = self._tool_records[key]
            start = self._tool_starts.pop(key)
            row.update(
                status=status,
                ended_at=_now(),
                duration_ms=round((perf_counter() - start) * 1000, 3),
            )
        for row in self.tool_calls:
            if row["status"] == "requested":
                row["status"] = "not_executed"

    def finish(self, status: str, error: Optional[BaseException] = None) -> None:
        self.close_tools("interrupted")
        if self.model_calls and self.model_calls[-1]["status"] == "running":
            self._usage_gap = True
            self.end_model(error=error or RuntimeError("Model request interrupted"))
        self.ended_at = _now()
        self.duration_ms = round((perf_counter() - self._start) * 1000, 3)
        self.status = status
        if error is not None:
            self.error = str(error) or type(error).__name__

    def to_dict(self) -> Dict[str, Any]:
        totals: Dict[str, Optional[int]] = {}
        reporting: Dict[str, int] = {}
        for name, field in TOKEN_FIELDS.items():
            values = [
                call["usage"][field] for call in self.model_calls
                if call.get("usage") is not None and call["usage"].get(field) is not None
            ]
            totals[name] = sum(values) if values else None
            reporting[name] = len(values)
        cache_writes = [
            call["cache_creation_input_tokens"] for call in self.model_calls
            if call.get("cache_creation_input_tokens") is not None
        ]
        totals["cache_creation_input_tokens"] = sum(cache_writes) if cache_writes else None
        reporting["cache_creation_input_tokens"] = len(cache_writes)
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "agent_duration_ms": self.agent_duration_ms,
            "status": self.status,
            "error": self.error,
            "attempt_count": self.attempt,
            "retry_count": max(0, self.attempt - 1),
            "model_call_count": len(self.model_calls),
            "tool_call_count": sum(row["started_at"] is not None for row in self.tool_calls),
            "usage_complete": bool(self.model_calls) and not self._usage_gap
            and reporting.get("total_tokens", 0) == len(self.model_calls),
            "token_totals": totals,
            "token_reporting": reporting,
            "model_calls": self.model_calls,
        }


active_metrics: ContextVar[Optional[InvestigationMetrics]] = ContextVar("investigation_metrics", default=None)


def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        metrics.start_model()


def after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        metrics.end_model(response=llm_response)


def model_error(callback_context: CallbackContext, llm_request: LlmRequest, error: Exception) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        metrics.end_model(error=error)


def before_tool(tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        call_id = getattr(tool_context, "function_call_id", None) or str(uuid4())
        tool_name = getattr(tool, "name", str(tool))
        metrics.start_tool(call_id, tool_name, args)


def after_tool(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, tool_response: Dict[str, Any],
) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        call_id = getattr(tool_context, "function_call_id", None)
        if call_id:
            metrics.end_tool(call_id, result=tool_response)


def tool_error(
    tool: BaseTool, args: Dict[str, Any], tool_context: ToolContext, error: Exception,
) -> None:
    metrics = active_metrics.get()
    if metrics is not None:
        call_id = getattr(tool_context, "function_call_id", None)
        if call_id:
            metrics.end_tool(call_id, error=error)
