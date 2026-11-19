import time
from typing import Any, Dict, List, Optional
from core.logging import logger


class ExecutionMetricsCollector:
    """Collects and computes execution telemetry, token consumption, and tool latencies during agent runs."""

    def __init__(self, model_name: str, alert_id: Optional[str] = None):
        self.model_name = model_name
        self.alert_id = alert_id
        self.start_time: float = time.time()
        self.end_time: Optional[float] = None

        self.prompt_tokens: int = 0
        self.candidates_tokens: int = 0
        self.total_tokens: int = 0
        self.cached_tokens: int = 0
        self.tool_use_tokens: int = 0
        self.thoughts_tokens: int = 0

        self.final_text: str = ""
        self.tool_calls_trace: List[Dict[str, Any]] = []
        self._tool_start_times: Dict[str, List[float]] = {}

    def process_event(self, event: Any) -> None:
        """Process an ADK runner lifecycle event to update token counts and tool invocations."""
        # 1. Capture token usage metadata
        if hasattr(event, "usage_metadata") and event.usage_metadata:
            um = event.usage_metadata
            self.prompt_tokens = getattr(um, "prompt_token_count", self.prompt_tokens) or self.prompt_tokens
            self.candidates_tokens = getattr(um, "candidates_token_count", self.candidates_tokens) or self.candidates_tokens
            self.total_tokens = getattr(um, "total_token_count", self.total_tokens) or self.total_tokens
            self.cached_tokens = getattr(um, "cached_content_token_count", self.cached_tokens) or self.cached_tokens
            self.tool_use_tokens = getattr(um, "tool_use_prompt_token_count", self.tool_use_tokens) or self.tool_use_tokens
            self.thoughts_tokens = getattr(um, "thoughts_token_count", self.thoughts_tokens) or self.thoughts_tokens

        # 2. Capture content parts (function calls, function responses, text)
        if hasattr(event, "content") and event.content:
            for part in event.content.parts:
                if getattr(part, "function_call", None):
                    fc = part.function_call
                    call_time = time.time()
                    self._tool_start_times.setdefault(fc.name, []).append(call_time)
                    logger.info(
                        f"Tool called: {fc.name}",
                        extra={"alert_id": self.alert_id, "tool_name": fc.name},
                    )
                    self.tool_calls_trace.append({
                        "type": "call",
                        "name": fc.name,
                        "args": fc.args,
                        "timestamp": call_time,
                    })

                elif getattr(part, "function_response", None):
                    fr = part.function_response
                    start_t = (
                        self._tool_start_times[fr.name].pop(0)
                        if self._tool_start_times.get(fr.name)
                        else time.time()
                    )
                    tool_duration_ms = round((time.time() - start_t) * 1000, 2)
                    logger.info(
                        f"Tool responded: {fr.name} ({tool_duration_ms}ms)",
                        extra={"alert_id": self.alert_id, "tool_name": fr.name},
                    )
                    self.tool_calls_trace.append({
                        "type": "response",
                        "name": fr.name,
                        "response": str(fr.response)[:5000],
                        "duration_ms": tool_duration_ms,
                        "timestamp": time.time(),
                    })

                elif getattr(part, "text", None):
                    self.final_text += part.text

    def get_duration_ms(self) -> float:
        """Return elapsed duration in milliseconds."""
        current_or_end = self.end_time or time.time()
        return round((current_or_end - self.start_time) * 1000, 2)

    def compute_metrics(self) -> Dict[str, Any]:
        """Compute consolidated, consistent execution metrics dictionary."""
        duration_ms = self.get_duration_ms()
        tool_responses = [t for t in self.tool_calls_trace if t.get("type") == "response"]
        total_tool_latency_ms = round(
            sum(t.get("duration_ms", 0.0) for t in tool_responses), 2
        )

        total_input_tokens = self.prompt_tokens + self.tool_use_tokens
        total_output_tokens = self.candidates_tokens + self.thoughts_tokens
        effective_total_tokens = self.total_tokens or (total_input_tokens + total_output_tokens)

        return {
            "duration_ms": duration_ms,
            "tool_latency_ms": total_tool_latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "tool_use_tokens": self.tool_use_tokens,
            "input_tokens": total_input_tokens,
            "candidates_tokens": self.candidates_tokens,
            "thoughts_tokens": self.thoughts_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": effective_total_tokens,
            "cached_tokens": self.cached_tokens,
            "tool_call_count": len([t for t in self.tool_calls_trace if t.get("type") == "call"]),
            "model": self.model_name,
        }
