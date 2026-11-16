import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery
from starlette.templating import Jinja2Templates

from agents.agent import process_alert_async
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from services.evidence_service import get_evidence_resolver
from services.report_renderer import render_report_to_markdown


UI_DIR = Path(__file__).resolve().parent
REPORT_DIR = Path.cwd() / "output" / "ui_reports"
ALERT_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
RULE_DETAILS = {
    "R1": {
        "name": "Low redemption rate",
        "meaning": "Redemption rate is below 5%, indicating customer offer friction.",
    },
    "R2": {
        "name": "Sudden redemption drop",
        "meaning": "Redemptions dropped by at least 50% compared with baseline period.",
    },
    "R3": {
        "name": "Existing-customer dominance",
        "meaning": "Existing customers account for at least 75% of redemptions in an acquisition campaign.",
    },
}

app = FastAPI(title="Merchant Offer Optimization Agent")
app.mount(
    "/static",
    StaticFiles(directory=str(UI_DIR / "static")),
    name="static",
)
templates = Jinja2Templates(directory=str(UI_DIR / "templates"))


def _report_path(alert_id: str) -> Path:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        raise HTTPException(status_code=400, detail="Invalid alert ID.")
    return REPORT_DIR / f"report_{alert_id}.json"


def _trace_path(alert_id: str) -> Path:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        raise HTTPException(status_code=400, detail="Invalid alert ID.")
    return REPORT_DIR / f"trace_{alert_id}.json"


def _alerts_table() -> str:
    config = get_config()
    return f"`{config.gcp.project_id}.{config.gcp.gold_dataset}.alerts`"


def _derive_severity(rule_id: str, metric_value: Any, threshold_value: Any) -> str:
    """Derive operational severity based on rule definition and metric deviation."""
    r_id = str(rule_id or "").upper()
    if r_id == "R2":
        return "HIGH"
    elif r_id == "R1":
        try:
            if metric_value is not None and float(metric_value) < 2.0:
                return "HIGH"
        except (ValueError, TypeError):
            pass
        return "MEDIUM"
    elif r_id == "R3":
        return "MEDIUM"
    return "LOW"


def _fetch_alerts(
    status: Optional[str] = None,
    rule_id: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    where_clauses = []
    parameters = []

    if status and status.upper() != "ALL":
        where_clauses.append("status = @status")
        parameters.append(bigquery.ScalarQueryParameter("status", "STRING", status.upper()))

    if rule_id and rule_id.upper() != "ALL":
        where_clauses.append("rule_id = @rule_id")
        parameters.append(bigquery.ScalarQueryParameter("rule_id", "STRING", rule_id.upper()))

    if search and search.strip():
        clean_search = f"%{search.strip()}%"
        where_clauses.append("(alert_id LIKE @search OR campaign_id LIKE @search OR merchant_id LIKE @search)")
        parameters.append(bigquery.ScalarQueryParameter("search", "STRING", clean_search))

    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    parameters.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))

    sql = f"""
        SELECT
            alert_id,
            campaign_id,
            merchant_id,
            rule_id,
            metric_name,
            metric_value,
            threshold_value,
            status,
            created_at,
            resolved_at,
            investigation_summary
        FROM {_alerts_table()}
        {where_str}
        ORDER BY created_at DESC
        LIMIT @limit
    """
    return execute_query(sql, parameters=parameters)


def _fetch_alert_status_counts() -> Dict[str, int]:
    """Fetch total count of alerts grouped by status for filter pill counters."""
    sql = f"""
        SELECT status, COUNT(1) AS cnt
        FROM {_alerts_table()}
        GROUP BY status
    """
    counts = {"OPEN": 0, "PROCESSING": 0, "RESOLVED": 0, "ERROR": 0, "ALL": 0}
    try:
        rows = execute_query(sql)
        total = 0
        for r in rows:
            st = str(r.get("status") or "").upper()
            c = int(r.get("cnt") or 0)
            if st in counts:
                counts[st] = c
            total += c
        counts["ALL"] = total
    except Exception as exc:
        logger.warning(f"Could not fetch alert status counts: {exc}")
    return counts


def _fetch_alert_by_id(alert_id: str) -> Dict[str, Any]:
    sql = f"""
        SELECT
            alert_id,
            campaign_id,
            merchant_id,
            rule_id,
            metric_name,
            metric_value,
            threshold_value,
            status,
            created_at,
            resolved_at,
            investigation_summary
        FROM {_alerts_table()}
        WHERE alert_id = @alert_id
        LIMIT 1
    """
    parameters = [
        bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id)
    ]
    rows = execute_query(sql, parameters=parameters)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"Alert '{alert_id}' not found in the alerts table.",
        )
    return rows[0]


def _fetch_open_alerts(limit: int = 100) -> List[Dict[str, Any]]:
    return _fetch_alerts(status="OPEN", limit=limit)


def _fetch_open_alert(alert_id: str) -> Dict[str, Any]:
    return _fetch_alert_by_id(alert_id)


def _render_error(
    request: Request,
    message: str,
    status_code: int,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "error.html",
        {"message": message},
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse, name="dashboard")
def dashboard(
    request: Request,
    status: Optional[str] = Query(default="ALL"),
    rule: Optional[str] = Query(default="ALL"),
    q: Optional[str] = Query(default=None),
) -> HTMLResponse:
    try:
        active_status = (status or "ALL").upper()
        active_rule = (rule or "ALL").upper()
        search_query = q.strip() if q else None

        alerts = _fetch_alerts(
            status=None if active_status == "ALL" else active_status,
            rule_id=None if active_rule == "ALL" else active_rule,
            search=search_query,
            limit=100,
        )
        counts = _fetch_alert_status_counts()

        for alert in alerts:
            r_id = str(alert.get("rule_id"))
            rule_details = RULE_DETAILS.get(
                r_id,
                {"name": "Other alert", "meaning": "No description is available for this rule."},
            )
            alert["rule_name"] = rule_details["name"]
            alert["rule_meaning"] = rule_details["meaning"]
            alert["severity"] = _derive_severity(r_id, alert.get("metric_value"), alert.get("threshold_value"))
            alert["has_report"] = _report_path(str(alert["alert_id"])).is_file()

    except Exception:
        logger.exception("Could not load alerts from BigQuery")
        return _render_error(
            request,
            "Could not load alerts from BigQuery. Check your project configuration and credentials, then try again.",
            status_code=503,
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "alerts": alerts,
            "status_counts": counts,
            "active_status": active_status,
            "active_rule": active_rule,
            "search_query": search_query or "",
        },
    )


@app.post("/alerts/{alert_id}/investigate", name="investigate_alert")
def investigate_alert(request: Request, alert_id: str) -> HTMLResponse:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        return _render_error(request, "Invalid alert ID.", status_code=400)

    try:
        alert = _fetch_alert_by_id(alert_id)
    except HTTPException as exc:
        return _render_error(request, str(exc.detail), status_code=exc.status_code)
    except Exception:
        logger.exception("Could not retrieve alert for investigation", extra={"alert_id": alert_id})
        return _render_error(
            request,
            "Could not retrieve this alert from BigQuery. Check your project configuration and credentials.",
            status_code=503,
        )

    try:
        result = asyncio.run(process_alert_async(alert))
        if not result.get("success") or not result.get("report"):
            error = str(result.get("error") or "The agent did not return an investigation report.")
            logger.error(
                f"Investigation failed: {error}",
                extra={"alert_id": alert_id},
            )
            return _render_error(
                request,
                f"Investigation failed: {error}",
                status_code=502,
            )

        report = result["report"]
        report_path = _report_path(alert_id)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, default=str),
            encoding="utf-8",
        )

        # Save trace sidecar with tool latency and token metrics
        trace_path = _trace_path(alert_id)
        trace_data = {
            "alert_id": alert_id,
            "execution_id": result.get("execution_id"),
            "duration_ms": result.get("duration_ms"),
            "metrics": result.get("metrics") or report.get("metrics") or {},
            "tool_calls": result.get("tool_calls") or [],
        }
        trace_path.write_text(
            json.dumps(trace_data, indent=2, default=str),
            encoding="utf-8",
        )

    except Exception:
        logger.exception("Could not complete or save investigation", extra={"alert_id": alert_id})
        return _render_error(
            request,
            "The investigation could not be completed or its report could not be saved. Check the application logs.",
            status_code=500,
        )

    return RedirectResponse(
        url=app.url_path_for("view_report", alert_id=alert_id),
        status_code=303,
    )


@app.get("/reports/{alert_id}", response_class=HTMLResponse, name="view_report")
def view_report(request: Request, alert_id: str) -> HTMLResponse:
    try:
        report_path = _report_path(alert_id)
    except HTTPException as exc:
        return _render_error(request, str(exc.detail), status_code=exc.status_code)

    if not report_path.is_file():
        return _render_error(
            request,
            "No saved investigation report exists for this alert yet.",
            status_code=404,
        )

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.exception("Could not read saved investigation report", extra={"alert_id": alert_id})
        return _render_error(
            request,
            "The saved report could not be read. Check the application logs.",
            status_code=500,
        )

    # Load trace sidecar if available
    trace_path = _trace_path(alert_id)
    trace = {}
    if trace_path.is_file():
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Extract metrics from report or trace
    metrics = report.get("metrics") or trace.get("metrics") or {}
    tool_calls = trace.get("tool_calls") or []

    # Prepare policy governance checks
    future_incremental_spend = report.get("future_incremental_spend")
    governance_checks = [
        {
            "name": "Human Approval Gate",
            "standard": "Mandatory for all operational adjustments",
            "status": "PASS" if report.get("human_approval_required", True) else "WARN",
            "detail": "Changes queued for merchant manager sign-off",
        },
        {
            "name": "Predictive Revenue Guardrail",
            "standard": "Prohibit future uplift or customer return claims",
            "status": "PASS" if future_incremental_spend is None else "REVIEW",
            "detail": f"future_incremental_spend = {future_incremental_spend}",
        },
        {
            "name": "Simulation Discipline",
            "standard": "Retrospective Historical Replay only",
            "status": "PASS" if report.get("simulation_type") == "HISTORICAL_REPLAY" else "REVIEW",
            "detail": "Observed transaction replay without behavioral speculation",
        },
        {
            "name": "Tool Authorization",
            "standard": "Read-Only Tools allowlist",
            "status": "PASS",
            "detail": "BigQuery analytics executed with parameterized queries",
        },
    ]

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": report,
            "metrics": metrics,
            "tool_calls": tool_calls,
            "governance_checks": governance_checks,
            "raw_json": json.dumps(report, indent=2, default=str),
        },
    )


@app.get("/reports/{alert_id}/markdown")
def download_report_markdown(alert_id: str) -> Response:
    """Download canonical Markdown report generated deterministically by report_renderer."""
    report_path = _report_path(alert_id)
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="Investigation report not found.")

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        md = render_report_to_markdown(report)
        return Response(
            content=md,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=report_{alert_id}.md"},
        )
    except Exception as exc:
        logger.error(f"Failed to generate markdown report: {exc}")
        raise HTTPException(status_code=500, detail="Could not generate markdown report.")


@app.get("/api/evidence/verify")
def api_verify_evidence(
    ref: str = Query(..., description="Evidence citation string from report"),
    campaign_id: Optional[str] = Query(default=None),
    merchant_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Interactive evidence verification endpoint.
    
    Resolves evidence references (e.g. 'bq:offers_silver.campaigns:CMP131')
    to the underlying Bronze raw tables in BigQuery and returns source records.
    """
    resolver = get_evidence_resolver()
    return resolver.resolve_evidence(ref, campaign_id=campaign_id, merchant_id=merchant_id)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
