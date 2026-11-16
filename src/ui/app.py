import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery
from starlette.templating import Jinja2Templates

# Load environment variables early and synchronize keys
load_dotenv()
if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = os.environ["GEMINI_API_KEY"]
elif os.environ.get("GOOGLE_API_KEY") and not os.environ.get("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = os.environ["GOOGLE_API_KEY"]

SRC_DIR = Path(__file__).resolve().parent.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agents.agent import process_alert_async
from agents.tools.bigquery_tools import get_campaign_terms
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger


UI_DIR = Path(__file__).resolve().parent
REPORT_DIR = Path.cwd() / "output" / "ui_reports"
ALERT_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")
RULE_DETAILS = {
    "R1": {
        "name": "Low redemption rate",
        "meaning": "Redemption rate is below 5%, indicating limited customer response.",
    },
    "R2": {
        "name": "Sudden redemption drop",
        "meaning": "Redemptions dropped by at least 50% compared with the baseline period.",
    },
    "R3": {
        "name": "Existing-customer dominance",
        "meaning": "Existing customers account for at least 75% of the share, which may limit new-customer acquisition.",
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


def _fetch_all_alerts(limit: int = 100) -> List[Dict[str, Any]]:
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
            created_at
        FROM {_alerts_table()}
        ORDER BY created_at DESC
        LIMIT @limit
    """
    parameters = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    return execute_query(sql, parameters=parameters)


def _fetch_alert(alert_id: str) -> Dict[str, Any]:
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
            created_at
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
            detail=f"Alert {alert_id} not found in BigQuery.",
        )
    return rows[0]


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
def dashboard(request: Request) -> HTMLResponse:
    banner_msg = request.query_params.get("msg")
    banner_count = request.query_params.get("count")
    try:
        alerts = _fetch_all_alerts(limit=100)
        for alert in alerts:
            rule_details = RULE_DETAILS.get(
                str(alert.get("rule_id")),
                {"name": "Other alert", "meaning": "No description is available for this rule."},
            )
            alert["rule_name"] = rule_details["name"]
            alert["rule_meaning"] = rule_details["meaning"]
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
            "banner_msg": banner_msg,
            "banner_count": banner_count,
        },
    )


@app.post("/alerts/trigger", name="trigger_alerts")
def trigger_alerts(request: Request) -> RedirectResponse:
    try:
        from alert import run_all_alerts, save_alerts_to_bigquery
        config = get_config()
        # Evaluate rules and capture any detected alerts
        new_alerts = run_all_alerts(config.gcp.project_id, filter_active=True)
        if new_alerts:
            save_alerts_to_bigquery(new_alerts, config.gcp.project_id)
            logger.info(f"Triggered and saved {len(new_alerts)} new alerts to BigQuery.")
            redirect_url = f"{app.url_path_for('dashboard')}?msg=triggered&count={len(new_alerts)}"
        else:
            logger.info("Triggered alerts check: no new alerts detected (existing alerts may already be active).")
            redirect_url = f"{app.url_path_for('dashboard')}?msg=no_new_alerts&count=0"
    except Exception as exc:
        logger.exception("Failed to trigger new alerts")
        return _render_error(
            request,
            f"Failed to trigger alert generation workflow: {exc}",
            status_code=500,
        )

    return RedirectResponse(url=redirect_url, status_code=303)


@app.post("/alerts/{alert_id}/investigate", name="investigate_alert")
def investigate_alert(request: Request, alert_id: str) -> HTMLResponse:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        return _render_error(request, "Invalid alert ID.", status_code=400)

    try:
        alert = _fetch_alert(alert_id)
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

        report_path = _report_path(alert_id)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result["report"], indent=2, default=str),
            encoding="utf-8",
        )

        # Save execution trace if present
        if result.get("trace"):
            trace_path = _trace_path(alert_id)
            trace_path.write_text(
                json.dumps(result["trace"], indent=2, default=str),
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

    # Load execution trace (from dedicated trace file or embedded in report)
    trace = None
    try:
        trace_path = _trace_path(alert_id)
        if trace_path.is_file():
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(f"Could not load trace file for alert {alert_id}: {exc}")

    if not trace and isinstance(report, dict):
        trace = report.get("execution_trace")

    # Load original campaign terms from BigQuery to compare against agent recommendations
    original_terms = None
    campaign_id = report.get("campaign_id")
    if campaign_id:
        try:
            terms_response = get_campaign_terms(str(campaign_id))
            if terms_response and terms_response.get("success") and terms_response.get("terms"):
                original_terms = terms_response["terms"]
        except Exception as exc:
            logger.warning(f"Could not fetch original campaign terms for {campaign_id}: {exc}")

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": report,
            "trace": trace,
            "original_terms": original_terms,
        },
    )


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
