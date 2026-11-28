"""Adapter helpers transforming agent dossiers and traces into EvalHub V1 JSON payloads."""

import ast
import json
from typing import Any, Dict, List, Optional, Tuple


def _parse_response_value(raw: Any) -> Any:
    """Parse serialized tool response string if possible, otherwise return as-is."""
    if not isinstance(raw, str):
        return raw
    stripped = raw.strip()
    if not stripped:
        return raw
    try:
        return json.loads(stripped)
    except Exception:
        try:
            return ast.literal_eval(stripped)
        except Exception:
            return raw


def _is_failed_tool_response(response: Any) -> bool:
    """Detect failure indicators inside a tool response payload."""
    parsed = _parse_response_value(response)
    if isinstance(parsed, dict):
        if parsed.get("success") is False or parsed.get("error"):
            return True
        if "allowed" in parsed and parsed.get("allowed") is False:
            return False  # validate_proposal returning allowed=False is a valid policy verdict
        return _is_failed_tool_response(parsed.get("result"))
    if isinstance(parsed, list):
        return any(_is_failed_tool_response(item) for item in parsed)
    resp_str = str(response)
    return "'success': False" in resp_str or '"success": false' in resp_str


def extract_alert_input(payload: Any) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Extract alert_id and optional full alert dict from an EvalHub POST payload.

    Supports:
    - {"alert_id": "ALT-123"}
    - {"alert_id": {"alert_id": "ALT-123", "campaign_id": "CMP131", ...}}
    - {"input": "ALT-123"} or {"input": {"alert_id": "ALT-123", ...}}
    - {"alert_id": "ALT-123", "campaign_id": "CMP131", "rule_id": "R1", ...}
    """
    if not isinstance(payload, dict):
        return "", None

    candidate: Any = payload.get("alert_id")
    if candidate is None and "input" in payload:
        candidate = payload.get("input")

    if isinstance(candidate, dict):
        alert_id = str(candidate.get("alert_id") or "").strip()
        if candidate.get("campaign_id") and candidate.get("rule_id"):
            merged = dict(candidate)
            merged.setdefault("status", "OPEN")
            return alert_id, merged
        return alert_id, None

    alert_id = str(candidate or "").strip()
    if payload.get("campaign_id") and payload.get("rule_id"):
        merged = dict(payload)
        merged["alert_id"] = alert_id
        merged.setdefault("status", "OPEN")
        return alert_id, merged

    return alert_id, None


def normalize_tool_calls_for_evalhub(
    tool_calls_trace: Optional[List[Dict[str, Any]]] = None,
    execution_metrics: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Convert paired ADK trace events or InvestigationMetrics tool records to EvalHub format."""
    if tool_calls_trace:
        normalized: List[Dict[str, Any]] = []
        pending_by_id: Dict[str, Dict[str, Any]] = {}
        pending_by_name: Dict[str, List[Dict[str, Any]]] = {}

        for idx, item in enumerate(tool_calls_trace, start=1):
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            name = str(item.get("name") or item.get("tool") or "unknown_tool")

            if item_type == "call":
                call_id = str(item.get("tool_call_id") or item.get("call_id") or f"call-{idx:03d}")
                record = {
                    "name": name,
                    "arguments": item.get("args") if "args" in item else (item.get("arguments") or {}),
                    "result": None,
                    "status": "unknown",
                    "call_id": call_id,
                }
                normalized.append(record)
                pending_by_id[call_id] = record
                pending_by_name.setdefault(name, []).append(record)

            elif item_type == "response":
                call_id = item.get("tool_call_id") or item.get("call_id")
                raw_resp = item.get("response") if "response" in item else item.get("result")
                status = "error" if _is_failed_tool_response(raw_resp) else "success"

                target = pending_by_id.pop(str(call_id), None) if call_id else None
                if target is None and pending_by_name.get(name):
                    target = pending_by_name[name].pop(0)
                    pending_by_id.pop(target["call_id"], None)
                elif target is not None and pending_by_name.get(name):
                    try:
                        pending_by_name[name].remove(target)
                    except ValueError:
                        pass

                if target is not None:
                    target["result"] = raw_resp
                    target["status"] = status
                else:
                    normalized.append({
                        "name": name,
                        "arguments": {},
                        "result": raw_resp,
                        "status": status,
                        "call_id": str(call_id or f"call-{idx:03d}"),
                    })
            else:
                # Already combined record
                raw_resp = item.get("result") if "result" in item else item.get("output")
                raw_status = str(item.get("status") or ("error" if _is_failed_tool_response(raw_resp) else "success")).lower()
                normalized.append({
                    "name": str(item.get("name") or item.get("tool") or "unknown_tool"),
                    "arguments": item.get("arguments") or item.get("args") or item.get("input") or {},
                    "result": raw_resp,
                    "status": "error" if raw_status in ("error", "failed", "cancelled") else "success" if raw_status == "success" else raw_status,
                    "call_id": str(item.get("call_id") or item.get("tool_call_id") or f"call-{idx:03d}"),
                })

        if normalized:
            return normalized

    metric_tools = (execution_metrics or {}).get("tool_calls") if isinstance(execution_metrics, dict) else None
    if isinstance(metric_tools, list):
        fallback: List[Dict[str, Any]] = []
        for idx, item in enumerate(metric_tools, start=1):
            if not isinstance(item, dict):
                continue
            raw_status = str(item.get("status") or "unknown").lower()
            fallback.append({
                "name": str(item.get("tool") or item.get("name") or "unknown_tool"),
                "arguments": item.get("input") or item.get("arguments") or {},
                "result": item.get("output") if "output" in item else item.get("result"),
                "status": "error" if raw_status in ("error", "failed", "cancelled") else raw_status,
                "call_id": str(item.get("tool_call_id") or item.get("call_id") or f"call-{idx:03d}"),
            })
        return fallback

    return []


def extract_root_cause(report: Dict[str, Any]) -> str:
    """Derive a concise root_cause string from InvestigationDossier hypotheses or summary."""
    explicit = report.get("root_cause")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    hypotheses = report.get("hypotheses") or []
    supported: List[str] = []
    for hyp in hypotheses:
        if isinstance(hyp, dict) and str(hyp.get("status", "")).upper() == "SUPPORTED":
            text = str(hyp.get("text") or "").strip()
            rationale = str(hyp.get("rationale") or "").strip()
            if text and rationale:
                supported.append(f"{text} ({rationale})")
            elif text:
                supported.append(text)
    if supported:
        return "; ".join(supported)

    return str(report.get("summary") or "").strip()


def format_findings(findings: Any) -> List[str]:
    """Convert structured Finding objects into EvalHub list[str] findings."""
    if not isinstance(findings, list):
        return []
    result: List[str] = []
    for item in findings:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
        elif isinstance(item, dict):
            obs = str(item.get("observation") or "").strip()
            if obs:
                result.append(obs)
    return result


def format_recommendations(recommendations: Any, proposal: Any = None) -> List[str]:
    """Convert structured RecommendationAction items (or proposal fallback) into list[str]."""
    result: List[str] = []
    if isinstance(recommendations, list):
        for item in recommendations:
            if isinstance(item, str) and item.strip():
                result.append(item.strip())
            elif isinstance(item, dict):
                action = str(item.get("action_type") or "ACTION").strip()
                params = item.get("parameter_changes")
                param_text = ""
                if isinstance(params, dict) and params:
                    param_text = " [" + ", ".join(f"{k}={v}" for k, v in params.items()) + "]"
                detail = str(item.get("expected_impact") or item.get("rationale") or "").strip()
                result.append(f"{action}{param_text}: {detail}" if detail else f"{action}{param_text}")

    if not result and isinstance(proposal, dict) and proposal.get("type"):
        p_type = str(proposal.get("type"))
        details = [f"{k}={proposal[k]}" for k in ("min_spend", "cashback_pct", "cashback_cap") if proposal.get(k) is not None]
        param_str = f" ({', '.join(details)})" if details else ""
        rationale = str(proposal.get("rationale") or "").strip()
        result.append(f"{p_type}{param_str}: {rationale}" if rationale else f"{p_type}{param_str}")

    return result


def format_evidence_used(evidence: Any) -> List[Dict[str, str]]:
    """Normalize EvidenceItem entries into EvalHub evidence_used objects."""
    if not isinstance(evidence, list):
        return []
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in evidence:
        if isinstance(item, dict):
            src = str(item.get("source") or "").strip()
            rec_id = str(item.get("record_id") or "").strip()
        elif isinstance(item, str):
            raw = item.replace("bq:", "").strip()
            parts = raw.split(":", 1)
            src = parts[0].strip()
            rec_id = parts[1].strip() if len(parts) > 1 else raw
        else:
            continue
        if src or rec_id:
            key = (src, rec_id)
            if key not in seen:
                seen.add(key)
                normalized.append({"source": src, "record_id": rec_id})
    return normalized


def format_evalhub_response(
    result: Dict[str, Any],
    alert: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the EvalHub V1 output payload from a process_alert_async result."""
    report = result.get("report") if isinstance(result.get("report"), dict) else {}
    tool_calls = normalize_tool_calls_for_evalhub(
        tool_calls_trace=result.get("tool_calls") or report.get("tool_calls"),
        execution_metrics=result.get("execution_metrics"),
    )
    evidence_items = report.get("evidence") or []

    return {
        "alert_id": report.get("alert_id") or result.get("alert_id") or (alert or {}).get("alert_id"),
        "campaign_id": report.get("campaign_id") or result.get("campaign_id") or (alert or {}).get("campaign_id"),
        "rule_id": report.get("rule_id") or result.get("rule_id") or (alert or {}).get("rule_id"),
        "status": report.get("status") or "COMPLETE",
        "summary": str(report.get("summary") or "").strip(),
        "root_cause": extract_root_cause(report),
        "findings": format_findings(report.get("findings")),
        "recommendations": format_recommendations(report.get("recommendations"), report.get("proposal")),
        "tool_calls": tool_calls,
        "evidence_used": format_evidence_used(evidence_items),
        "evidence": evidence_items,
        "proposal": report.get("proposal"),
        "future_incremental_spend": report.get("future_incremental_spend"),
        "human_approval_required": report.get("human_approval_required", True),
    }
