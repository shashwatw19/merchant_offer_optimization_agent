import asyncio
from datetime import date, datetime, timedelta
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery
from starlette.templating import Jinja2Templates

from agents.agent import process_alert_async
from services.alert_store import update_alert_status
from agents.tools.bigquery_tools import get_campaign_terms
from services.report_converter import convert_json_report_to_markdown
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from services.gcs_storage import get_storage_service

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
METRIC_DETAILS = {
    "redemption_rate": {
        "title": "Redemption Rate",
        "description": "% of targeted customers who redeemed",
        "detail": "Tracks the percentage of targeted audience customers who completed qualifying purchases and claimed cashback.",
    },
    "period_redemption_drop_pct": {
        "title": "Period Rate Drop",
        "description": "% drop in second half vs. baseline",
        "detail": "Tracks sudden velocity drop between the campaign's first half baseline and second half runtime.",
    },
    "existing_customer_share_pct": {
        "title": "Existing Customer Share",
        "description": "% of redeemers who are repeat customers",
        "detail": "Tracks whether an acquisition campaign is being cannibalized by pre-existing shoppers rather than acquiring new customers.",
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
    steps: List[Dict[str, Any]] = []
    # Map of tool_name -> list of uncompleted step dicts (FIFO queue for parallel tool calling)
    pending_calls: Dict[str, List[Dict[str, Any]]] = {}
    step_num = 1

    for item in tool_calls:
        item_type = item.get("type")
        name = item.get("name", "tool")

        if item_type == "call":
            step = {
                "step_number": step_num,
                "tool_name": name,
                "purpose": TOOL_PURPOSES.get(name, "Execute investigation tool query"),
                "args": item.get("args") or {},
                "duration_ms": None,
                "status": "SUCCESS",
                "response_summary": "",
            }
            steps.append(step)
            pending_calls.setdefault(name, []).append(step)
            step_num += 1

        elif item_type == "response":
            matching_steps = pending_calls.get(name, [])
            if matching_steps:
                # Match with the oldest open call for this tool (FIFO)
                step = matching_steps.pop(0)
                step["duration_ms"] = item.get("duration_ms")
                resp_str = str(item.get("response", ""))
                is_failed = "'success': False" in resp_str or '"success": false' in resp_str
                if is_failed:
                    step["status"] = "FAILED"
                step["response_summary"] = resp_str[:250]
            else:
                # Fallback for an unexpected response with no preceding call
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
            # Standalone or pre-merged step format
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
    candidate_paths = [
        REPORT_DIR / f"report_{alert_id}.json",
        Path.cwd() / "output" / f"report_{alert_id}.json",
        Path.cwd() / "output" / "reports" / f"report_{alert_id}.json",
        Path.cwd() / "output" / "ui_reports" / f"report_{alert_id}.json",
    ]
    for p in candidate_paths:
        if p.is_file():
            return p
    return REPORT_DIR / f"report_{alert_id}.json"


def _alerts_table() -> str:
    config = get_config()
    return f"`{config.gcp.project_id}.{config.gcp.gold_dataset}.alerts`"


def _compute_campaign_timeline(start_date_val: Any, end_date_val: Any) -> Dict[str, Any]:
    """Calculate campaign midpoint, Period 1 (baseline/threshold) window, and Period 2 (evaluation/metric) window."""
    if not start_date_val or not end_date_val:
        return {
            "start_date": "Campaign Start",
            "end_date": "Campaign End",
            "mid_date": "Midpoint",
            "p1_label": "Period 1 (First Half / Baseline)",
            "p2_label": "Period 2 (Second Half / Evaluation)",
            "total_days": None,
        }
    try:
        s_date = None
        e_date = None

        if isinstance(start_date_val, str):
            s_date = datetime.strptime(start_date_val.split("T")[0], "%Y-%m-%d").date()
        elif isinstance(start_date_val, datetime):
            s_date = start_date_val.date()
        elif isinstance(start_date_val, date):
            s_date = start_date_val

        if isinstance(end_date_val, str):
            e_date = datetime.strptime(end_date_val.split("T")[0], "%Y-%m-%d").date()
        elif isinstance(end_date_val, datetime):
            e_date = end_date_val.date()
        elif isinstance(end_date_val, date):
            e_date = end_date_val

        if not s_date or not e_date:
            return {
                "start_date": str(start_date_val),
                "end_date": str(end_date_val),
                "mid_date": "Midpoint",
                "p1_label": f"{start_date_val} to Midpoint",
                "p2_label": f"Midpoint to {end_date_val}",
                "total_days": None,
            }

        total_days = max(1, (e_date - s_date).days)
        mid_days = total_days // 2
        mid_date = s_date + timedelta(days=mid_days)
        p2_start = mid_date + timedelta(days=1) if mid_date < e_date else mid_date

        return {
            "start_date": s_date.strftime("%Y-%m-%d"),
            "end_date": e_date.strftime("%Y-%m-%d"),
            "mid_date": mid_date.strftime("%Y-%m-%d"),
            "p1_start": s_date.strftime("%Y-%m-%d"),
            "p1_end": mid_date.strftime("%Y-%m-%d"),
            "p2_start": p2_start.strftime("%Y-%m-%d"),
            "p2_end": e_date.strftime("%Y-%m-%d"),
            "p1_label": f"{s_date.strftime('%Y-%m-%d')} to {mid_date.strftime('%Y-%m-%d')}",
            "p2_label": f"{p2_start.strftime('%Y-%m-%d')} to {e_date.strftime('%Y-%m-%d')}",
            "total_days": total_days,
        }
    except Exception as exc:
        logger.warning(f"Error computing campaign timeline: {exc}")
        return {
            "start_date": str(start_date_val),
            "end_date": str(end_date_val),
            "mid_date": "Midpoint",
            "p1_label": f"{start_date_val} (P1)",
            "p2_label": f"{end_date_val} (P2)",
            "total_days": None,
        }


def _fetch_alerts(limit: int = 100) -> List[Dict[str, Any]]:
    config = get_config()
    campaigns_table = f"`{config.gcp.project_id}.{config.gcp.silver_dataset}.campaigns`"
    try:
        sql = f"""
            SELECT
                a.alert_id,
                a.campaign_id,
                a.merchant_id,
                a.rule_id,
                a.metric_name,
                a.metric_value,
                a.threshold_value,
                a.status,
                a.created_at,
                c.start_date,
                c.end_date
            FROM {_alerts_table()} a
            LEFT JOIN {campaigns_table} c
              ON a.campaign_id = c.campaign_id
            ORDER BY a.created_at DESC
            LIMIT @limit
        """
        parameters = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]
        rows = execute_query(sql, parameters=parameters)
        for r in rows:
            for k in ("start_date", "end_date", "created_at"):
                if hasattr(r.get(k), "isoformat"):
                    r[k] = r[k].isoformat()
        return rows
    except Exception as exc:
        logger.warning(f"Alerts query with campaigns join failed ({exc}), falling back to direct alerts table...")
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


_fetch_open_alerts = _fetch_alerts


def _fetch_alert_status_counts() -> Dict[str, int]:
    return {"OPEN": 0, "ALL": 0, "RESOLVED": 0, "PROCESSING": 0, "ERROR": 0}


def _fetch_open_alert(alert_id: str) -> Dict[str, Any]:
    config = get_config()
    campaigns_table = f"`{config.gcp.project_id}.{config.gcp.silver_dataset}.campaigns`"
    try:
        sql = f"""
            SELECT
                a.alert_id,
                a.campaign_id,
                a.merchant_id,
                a.rule_id,
                a.metric_name,
                a.metric_value,
                a.threshold_value,
                a.status,
                a.created_at,
                c.start_date,
                c.end_date
            FROM {_alerts_table()} a
            LEFT JOIN {campaigns_table} c
              ON a.campaign_id = c.campaign_id
            WHERE a.alert_id = @alert_id
            LIMIT 1
        """
        parameters = [
            bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id)
        ]
        rows = execute_query(sql, parameters=parameters)
        if rows:
            row = dict(rows[0])
            for k in ("start_date", "end_date", "created_at"):
                if hasattr(row.get(k), "isoformat"):
                    row[k] = row[k].isoformat()
            return row
    except Exception as exc:
        logger.warning(f"Open alert query with campaigns join failed ({exc}), falling back...")

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
            detail="Alert not found. It may have been removed or does not exist.",
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
            aid = str(alert.get("alert_id"))
            rule_details = RULE_DETAILS.get(
                str(alert.get("rule_id")),
                {"name": "Other alert", "meaning": "No description is available for this rule."},
            )
            alert["rule_name"] = rule_details["name"]
            alert["rule_meaning"] = rule_details["meaning"]

            # Attach friendly metric labels and descriptions
            m_info = METRIC_DETAILS.get(
                str(alert.get("metric_name")),
                {
                    "title": str(alert.get("metric_name") or "—").replace("_", " ").title(),
                    "description": "Campaign performance metric",
                    "detail": "Operational metric tracking campaign performance.",
                },
            )
            alert["metric_title"] = m_info["title"]
            alert["metric_description"] = m_info["description"]
            alert["metric_detail"] = m_info["detail"]

            report_file = _report_path(aid)
            alert["has_report"] = report_file.is_file()

            # Attach investigation summary if report is present
            if alert["has_report"] and not alert.get("summary"):
                try:
                    rep_data = json.loads(report_file.read_text(encoding="utf-8"))
                    alert["summary"] = rep_data.get("summary")
                    if not alert.get("start_date") and rep_data.get("campaign_terms"):
                        alert["start_date"] = rep_data["campaign_terms"].get("start_date")
                        alert["end_date"] = rep_data["campaign_terms"].get("end_date")
                except Exception:
                    pass

            # Compute campaign timeline (especially for R2 split-window detection)
            s_date = alert.get("start_date")
            e_date = alert.get("end_date")
            if (not s_date or not e_date) and alert.get("campaign_id"):
                try:
                    terms_res = get_campaign_terms(alert["campaign_id"])
                    if terms_res.get("terms"):
                        t = terms_res["terms"]
                        s_date = s_date or t.get("start_date")
                        e_date = e_date or t.get("end_date")
                        alert["start_date"] = s_date
                        alert["end_date"] = e_date
                except Exception:
                    pass
            alert["timeline"] = _compute_campaign_timeline(s_date, e_date)
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
async def investigate_alert(request: Request, alert_id: str) -> HTMLResponse:
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
        result = await process_alert_async(alert)
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

        exec_id = report_data.get("execution_id") or result.get("execution_id") or f"exec_{alert_id}"
        report_data["execution_id"] = exec_id

        # Upload canonical JSON and Markdown reports to GCS
        try:
            storage_service = get_storage_service()
            gcs_json_res = storage_service.upload_json(
                report_data=report_data,
                execution_id=exec_id,
                alert_id=alert_id,
                campaign_id=cid,
            )
            if gcs_json_res.success and not gcs_json_res.is_fallback:
                report_data["gcs_json_uri"] = gcs_json_res.uri
                logger.info(f"Uploaded canonical JSON report to GCS: {gcs_json_res.uri}")

            md_file = report_path.with_suffix(".md")
            md_res = convert_json_report_to_markdown(
                report_data=report_data,
                execution_id=exec_id,
                output_path=str(md_file),
                save_to_gcs=True,
            )
            if md_res.get("success") and md_res.get("gcs_uri"):
                report_data["gcs_markdown_uri"] = md_res.get("gcs_uri")
                logger.info(f"Uploaded Markdown report to GCS: {md_res.get('gcs_uri')}")
        except Exception as exc:
            logger.warning(f"Could not upload report to GCS (falling back to local storage): {exc}")

        # Save local JSON report (including any GCS URIs recorded)
        report_path.write_text(
            json.dumps(report_data, indent=2, default=str),
            encoding="utf-8",
        )

        # Update BigQuery alert record with investigation summary
        summary_text = report_data.get("summary") or "Investigation completed successfully."
        try:
            update_alert_status(alert_id=alert_id, status="RESOLVED", summary=summary_text)
            logger.info(f"Recorded investigation summary for alert {alert_id} in BigQuery.")
        except Exception as exc:
            logger.warning(f"Could not update BigQuery alert summary: {exc}")
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
    if metrics:
        prompt_t = metrics.get("prompt_tokens", 0) or 0
        cand_t = metrics.get("candidates_tokens", 0) or 0
        total_t = metrics.get("total_tokens", 0) or 0
        tool_t = metrics.get("tool_use_tokens", 0) or 0
        thought_t = metrics.get("thoughts_tokens", 0) or 0

        # Auto-reconcile for legacy saved reports where tool_use wasn't separated from total
        if not tool_t and not thought_t and total_t > (prompt_t + cand_t):
            tool_t = total_t - (prompt_t + cand_t)
            metrics["tool_use_tokens"] = tool_t

        if "input_tokens" not in metrics:
            metrics["input_tokens"] = prompt_t + tool_t
        if "output_tokens" not in metrics:
            metrics["output_tokens"] = cand_t + thought_t

    tool_calls = report.get("tool_calls") or []
    execution_steps = _build_execution_steps(tool_calls)

    # Derive timeline and alert metadata
    alert_row = None
    try:
        alert_row = _fetch_open_alert(alert_id)
    except Exception:
        pass

    s_date = None
    e_date = None
    if campaign_terms:
        s_date = campaign_terms.get("start_date")
        e_date = campaign_terms.get("end_date")
    if (not s_date or not e_date) and alert_row:
        s_date = s_date or alert_row.get("start_date")
        e_date = e_date or alert_row.get("end_date")

    timeline = _compute_campaign_timeline(s_date, e_date)

    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "report": report,
            "campaign_terms": campaign_terms,
            "metrics": metrics,
            "tool_calls": tool_calls,
            "execution_steps": execution_steps,
            "alert": alert_row,
            "timeline": timeline,
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
