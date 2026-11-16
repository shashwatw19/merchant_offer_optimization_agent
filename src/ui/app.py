import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery
from starlette.templating import Jinja2Templates

from agents.agent import process_alert_async
from agents.tools.bigquery_tools import get_campaign_terms
from agents.tools.report_tools import convert_json_report_to_markdown
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger

# Configure GCP project and location identical to bigquery_client
_config = get_config()
_gcp_project = getattr(getattr(_config, "gcp", None), "project_id", "prj-imp-act-campaign")
_gcp_location = getattr(getattr(_config, "gcp", None), "location", "asia-south1")

if "GOOGLE_CLOUD_PROJECT" not in os.environ and _gcp_project:
    os.environ["GOOGLE_CLOUD_PROJECT"] = _gcp_project
if "GCP_PROJECT" not in os.environ and _gcp_project:
    os.environ["GCP_PROJECT"] = _gcp_project
if "GOOGLE_CLOUD_LOCATION" not in os.environ and _gcp_location:
    os.environ["GOOGLE_CLOUD_LOCATION"] = _gcp_location

# If API key is present in environment, sync it; otherwise use Google Cloud Vertex AI credentials like BigQuery
_ENV_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if _ENV_API_KEY:
    os.environ["GEMINI_API_KEY"] = _ENV_API_KEY
    os.environ["GOOGLE_API_KEY"] = _ENV_API_KEY
else:
    os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"


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

TOOL_PURPOSES = {
    "get_campaign_terms": "Retrieve merchant campaign parameters, objective, and rules",
    "get_campaign_performance": "Fetch audience reach, send counts, and redemption metrics",
    "get_spend_distribution": "Analyze merchant historical transaction profile and ticket sizes",
    "get_customer_reviews": "Inspect customer reviews, sentiment, and satisfaction ratings",
    "get_merchant_feedback": "Check merchant operational notes, incidents, and relationship status",
    "get_delivery_metrics": "Evaluate communication delivery rates and geographic audience alignment",
    "get_comparable_campaigns": "Benchmark redemption performance against category peer campaigns",
    "validate_proposal": "Validate proposed parameter modifications against business policy rules",
    "simulate_campaign_change": "Run retrospective historical replay simulation on card transactions",
}


def _build_execution_steps(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    steps = []
    current_step = None
    step_num = 1
    for item in tool_calls:
        item_type = item.get("type")
        name = item.get("name", "tool")
        if item_type == "call":
            if current_step:
                steps.append(current_step)
            current_step = {
                "step_number": step_num,
                "tool_name": name,
                "purpose": TOOL_PURPOSES.get(name, "Execute investigation tool query"),
                "args": item.get("args") or {},
                "duration_ms": None,
                "status": "SUCCESS",
                "response_summary": "",
            }
            step_num += 1
        elif item_type == "response":
            if current_step and current_step["tool_name"] == name:
                current_step["duration_ms"] = item.get("duration_ms")
                resp_str = str(item.get("response", ""))
                is_failed = "'success': False" in resp_str or '"success": false' in resp_str
                if is_failed:
                    current_step["status"] = "FAILED"
                current_step["response_summary"] = resp_str[:250]
                steps.append(current_step)
                current_step = None
            else:
                resp_str = str(item.get("response", ""))
                is_failed = "'success': False" in resp_str or '"success": false' in resp_str
                steps.append({
                    "step_number": step_num,
                    "tool_name": name,
                    "purpose": TOOL_PURPOSES.get(name, "Execute investigation tool query"),
                    "args": {},
                    "duration_ms": item.get("duration_ms"),
                    "status": "FAILED" if is_failed else "SUCCESS",
                    "response_summary": resp_str[:250],
                })
                step_num += 1
        else:
            steps.append({
                "step_number": step_num,
                "tool_name": name,
                "purpose": TOOL_PURPOSES.get(name, "Execute investigation tool query"),
                "args": item.get("args") or {},
                "duration_ms": item.get("duration_ms"),
                "status": item.get("status", "SUCCESS"),
                "response_summary": str(item.get("response") or item.get("response_summary", ""))[:250],
            })
            step_num += 1
    if current_step:
        steps.append(current_step)
    return steps


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


def _alerts_table() -> str:
    config = get_config()
    return f"`{config.gcp.project_id}.{config.gcp.gold_dataset}.alerts`"


def _fetch_open_alerts(limit: int) -> List[Dict[str, Any]]:
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
        WHERE status = 'OPEN'
        ORDER BY created_at DESC
        LIMIT @limit
    """
    parameters = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    return execute_query(sql, parameters=parameters)


_fetch_alerts = _fetch_open_alerts


def _fetch_alert_status_counts() -> Dict[str, int]:
    return {"OPEN": 0, "ALL": 0, "RESOLVED": 0, "PROCESSING": 0, "ERROR": 0}


def _fetch_open_alert(alert_id: str) -> Dict[str, Any]:
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
        WHERE alert_id = @alert_id AND status = 'OPEN'
        LIMIT 1
    """
    parameters = [
        bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id)
    ]
    rows = execute_query(sql, parameters=parameters)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Open alert not found. It may have been removed or already processed.",
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
    try:
        alerts = _fetch_alerts(limit=100)
        for alert in alerts:
            rule_details = RULE_DETAILS.get(
                str(alert.get("rule_id")),
                {"name": "Other alert", "meaning": "No description is available for this rule."},
            )
            alert["rule_name"] = rule_details["name"]
            alert["rule_meaning"] = rule_details["meaning"]
            alert["has_report"] = _report_path(str(alert["alert_id"])).is_file()
    except Exception:
        logger.exception("Could not load open alerts")
        return _render_error(
            request,
            "Could not load alerts from BigQuery. Check your project configuration and credentials, then try again.",
            status_code=503,
        )

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"alerts": alerts},
    )


@app.post("/alerts/{alert_id}/investigate", name="investigate_alert")
def investigate_alert(request: Request, alert_id: str) -> HTMLResponse:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        return _render_error(request, "Invalid alert ID.", status_code=400)

    # Configure GCP environment identical to bigquery_client
    cfg = get_config()
    target_project = getattr(getattr(cfg, "gcp", None), "project_id", "prj-imp-act-campaign")
    target_location = getattr(getattr(cfg, "gcp", None), "location", "asia-south1")
    if target_project:
        os.environ["GOOGLE_CLOUD_PROJECT"] = target_project
        os.environ["GCP_PROJECT"] = target_project
    if target_location:
        os.environ["GOOGLE_CLOUD_LOCATION"] = target_location

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        os.environ["GOOGLE_API_KEY"] = api_key
    else:
        # Use Google Cloud Vertex AI credentials (ADC / IAM), identical to BigQuery client
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"

    try:
        alert = _fetch_open_alert(alert_id)
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

        report_data = result["report"]
        if "tool_calls" not in report_data and "tool_calls" in result:
            report_data["tool_calls"] = result["tool_calls"]
        if "metrics" not in report_data and "metrics" in result:
            report_data["metrics"] = result["metrics"]

        cid = report_data.get("campaign_id") or alert.get("campaign_id")
        if cid and not report_data.get("campaign_terms"):
            try:
                terms_res = get_campaign_terms(cid)
                if terms_res.get("success") and terms_res.get("terms"):
                    report_data["campaign_terms"] = terms_res.get("terms")
            except Exception as exc:
                logger.warning(f"Could not load campaign terms for {cid}: {exc}")

        report_path = _report_path(alert_id)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report_data, indent=2, default=str),
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

    campaign_terms = report.get("campaign_terms")
    if not campaign_terms and report.get("campaign_id"):
        try:
            terms_res = get_campaign_terms(report["campaign_id"])
            if terms_res.get("success") and terms_res.get("terms"):
                campaign_terms = terms_res.get("terms")
                report["campaign_terms"] = campaign_terms
        except Exception as exc:
            logger.warning(f"Could not load campaign terms for {report.get('campaign_id')}: {exc}")

    metrics = report.get("metrics") or {}
    tool_calls = report.get("tool_calls") or []
    execution_steps = _build_execution_steps(tool_calls)

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": report,
            "campaign_terms": campaign_terms,
            "metrics": metrics,
            "tool_calls": tool_calls,
            "execution_steps": execution_steps,
        },
    )


@app.get("/reports/{alert_id}/markdown", response_class=PlainTextResponse, name="download_report_markdown")
def download_report_markdown(alert_id: str) -> PlainTextResponse:
    try:
        report_path = _report_path(alert_id)
    except HTTPException as exc:
        raise exc

    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="No saved investigation report exists for this alert.")

    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        res = convert_json_report_to_markdown(report_data=report_data, save_to_gcs=False)
        return PlainTextResponse(content=res.get("markdown_content", ""), media_type="text/markdown")
    except Exception as exc:
        logger.exception("Failed to render markdown report", extra={"alert_id": alert_id})
        raise HTTPException(status_code=500, detail="Could not render markdown report.")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
