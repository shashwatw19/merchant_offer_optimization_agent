import asyncio
from datetime import date, datetime, timedelta
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import bigquery
from starlette.templating import Jinja2Templates

from agents.agent import process_alert_async, _enrich_dossier_from_traces, _clean_currency_text
from agents.tools.bigquery_tools import get_campaign_terms
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger
from services.alert_store import update_alert_status
from services.report_converter import convert_json_report_to_markdown
from services.run_store import ensure_agent_runs_table


UI_DIR = Path(__file__).resolve().parent
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
                step = matching_steps.pop(0)
                step["duration_ms"] = item.get("duration_ms")
                resp_str = str(item.get("response", ""))
                is_failed = "'success': False" in resp_str or '"success": false' in resp_str
                if is_failed:
                    step["status"] = "FAILED"
                step["response_summary"] = resp_str[:250]
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

    return steps


app = FastAPI(title="Merchant Offer Optimization Agent")
app.mount(
    "/static",
    StaticFiles(directory=str(UI_DIR / "static")),
    name="static",
)
templates = Jinja2Templates(directory=str(UI_DIR / "templates"))


def _alerts_table() -> str:
    config = get_config()
    return f"`{config.gcp.project_id}.{config.gcp.gold_dataset}.alerts`"


def _agent_runs_table() -> str:
    cfg = get_config()
    proj = getattr(getattr(cfg, "gcp", None), "project_id", "prj-imp-act-campaign")
    gold = getattr(getattr(cfg, "gcp", None), "gold_dataset", "offers_gold")
    default_table = f"{proj}.{gold}.agent_runs"
    configured_table = getattr(getattr(cfg, "audit", None), "runs_table", None) or default_table
    if "." not in configured_table:
        configured_table = f"{gold}.{configured_table}"
    return configured_table


_RUN_KEY_SQL = """COALESCE(run_id, CONCAT('legacy-', TO_HEX(SHA256(
    CONCAT(alert_id, '|', CAST(run_time AS STRING), '|', CAST(run_number AS STRING))
))))"""


def _admin_json(value: Any, expected_type: type) -> Any:
    if value is None:
        return None
    if isinstance(value, expected_type):
        return value
    try:
        decoded = json.loads(value)
        if decoded is not None and not isinstance(decoded, expected_type):
            return decoded
        return decoded
    except (ValueError, TypeError):
        return None


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
    merchants_table = f"`{config.gcp.project_id}.{config.gcp.silver_dataset}.merchants`"
    agent_runs = _agent_runs_table()
    try:
        sql = f"""
            SELECT
                a.alert_id,
                a.campaign_id,
                a.merchant_id,
                m.name AS merchant_name,
                a.rule_id,
                a.metric_name,
                a.metric_value,
                a.threshold_value,
                a.status,
                a.created_at,
                c.start_date,
                c.end_date,
                r.run_number,
                r.recommendation,
                r.confidence,
                r.run_time_ist,
                r.summary AS run_summary
            FROM {_alerts_table()} a
            LEFT JOIN {campaigns_table} c
              ON a.campaign_id = c.campaign_id
            LEFT JOIN {merchants_table} m
              ON a.merchant_id = m.merchant_id
            LEFT JOIN (
              SELECT
                alert_id,
                run_number,
                recommendation,
                confidence,
                FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S IST', run_time, 'Asia/Kolkata') AS run_time_ist,
                JSON_VALUE(output_json, '$.summary') AS summary
              FROM `{agent_runs}`
              WHERE recommendation != 'FAILED'
              QUALIFY ROW_NUMBER() OVER(PARTITION BY alert_id ORDER BY run_time DESC) = 1
            ) r ON a.alert_id = r.alert_id
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
        logger.warning(f"Alerts query with campaigns/merchants/agent_runs join failed ({exc}), falling back...")
        sql = f"""
            SELECT
                a.alert_id,
                a.campaign_id,
                a.merchant_id,
                m.name AS merchant_name,
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
            LEFT JOIN {merchants_table} m
              ON a.merchant_id = m.merchant_id
            ORDER BY a.created_at DESC
            LIMIT @limit
        """
        try:
            parameters = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]
            rows = execute_query(sql, parameters=parameters)
            for r in rows:
                for k in ("start_date", "end_date", "created_at"):
                    if hasattr(r.get(k), "isoformat"):
                        r[k] = r[k].isoformat()
            return rows
        except Exception:
            sql_fallback = f"""
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
            return execute_query(sql_fallback, parameters=parameters)


_fetch_open_alerts = _fetch_alerts


def _fetch_agent_run_report(alert_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves full investigation dossier and execution metadata directly from agent_runs table."""
    table_id = _agent_runs_table()
    clean_id = alert_id.strip()
    query = f"""
    SELECT
      run_number,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S IST', run_time, 'Asia/Kolkata') AS run_time_ist,
      recommendation,
      confidence,
      duration_ms,
      batch_id,
      campaign_id,
      run_status,
      TO_JSON_STRING(tool_calls) AS tool_calls_json,
      TO_JSON_STRING(output_json) AS output_json_str,
      TO_JSON_STRING(execution_metrics) AS metrics_json
    FROM `{table_id}`
    WHERE alert_id = @alert_id AND recommendation != 'FAILED'
    ORDER BY run_time DESC
    LIMIT 1
    """
    try:
        ensure_agent_runs_table()
        params = [bigquery.ScalarQueryParameter("alert_id", "STRING", clean_id)]
        rows = execute_query(query, parameters=params)
        if not rows:
            return None

        run = dict(rows[0])
        report: Dict[str, Any] = {}
        if run.get("output_json_str"):
            try:
                parsed = json.loads(run["output_json_str"])
                if isinstance(parsed, dict):
                    report = parsed
            except Exception as exc:
                logger.warning(f"Could not parse output_json from agent_runs: {exc}")

        # Clean raw JSON/markdown artifacts in summary if present
        if report.get("summary"):
            s_val = str(report["summary"])
            if "```json" in s_val or s_val.strip().startswith("{"):
                m_sum = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', s_val)
                if m_sum:
                    report["summary"] = m_sum.group(1).encode().decode("unicode_escape", "ignore").strip()
                else:
                    report["summary"] = re.sub(r"```(?:json)?\s*", "", s_val).replace("```", "").strip()

        # Attach execution metrics & tool calls
        if run.get("tool_calls_json"):
            try:
                tc = json.loads(run["tool_calls_json"])
                if isinstance(tc, list):
                    report["tool_calls"] = tc
            except Exception:
                pass

        if run.get("metrics_json"):
            try:
                em = json.loads(run["metrics_json"])
                if isinstance(em, dict):
                    report["metrics"] = em
            except Exception:
                pass

        if not report.get("alert_id"):
            report["alert_id"] = clean_id
        if not report.get("campaign_id") and run.get("campaign_id"):
            report["campaign_id"] = run["campaign_id"]
        if not report.get("status"):
            report["status"] = run.get("confidence") or "COMPLETE"
        if not report.get("generated_at") and run.get("run_time_ist"):
            report["generated_at"] = run["run_time_ist"]

        # Clean currency encoding artifacts
        if report.get("summary"):
            report["summary"] = _clean_currency_text(report["summary"])

        # Trace-backed enrichment: If hypotheses or findings were empty/stubbed in historical runs, enrich from tool_calls
        if (not report.get("hypotheses") or len(report.get("findings", [])) <= 1) and report.get("tool_calls"):
            report = _enrich_dossier_from_traces(
                parsed=report,
                alert={"alert_id": clean_id, "campaign_id": report.get("campaign_id") or run.get("campaign_id")},
                tool_calls_trace=report.get("tool_calls", []),
                final_text=report.get("summary", ""),
                exec_id=report.get("execution_id") or f"exec_{clean_id}",
                now_str=report.get("generated_at") or run.get("run_time_ist") or "",
                metrics=report.get("metrics") or {},
            )

        return report
    except Exception as exc:
        logger.warning(f"Could not fetch investigation report from agent_runs ({exc})")
        return None


def _fetch_alert_status_counts() -> Dict[str, int]:
    return {"OPEN": 0, "ALL": 0, "RESOLVED": 0, "PROCESSING": 0, "ERROR": 0}


def _fetch_open_alert(alert_id: str) -> Dict[str, Any]:
    config = get_config()
    campaigns_table = f"`{config.gcp.project_id}.{config.gcp.silver_dataset}.campaigns`"
    merchants_table = f"`{config.gcp.project_id}.{config.gcp.silver_dataset}.merchants`"
    try:
        sql = f"""
            SELECT
                a.alert_id,
                a.campaign_id,
                a.merchant_id,
                m.name AS merchant_name,
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
            LEFT JOIN {merchants_table} m
              ON a.merchant_id = m.merchant_id
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
        logger.warning(f"Open alert query with campaigns/merchants join failed ({exc}), falling back...")

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

            has_run = bool(alert.get("run_number") or alert.get("run_summary"))
            alert["has_report"] = has_run

            # Attach investigation summary if report is present in BigQuery
            if not alert.get("summary") and alert.get("run_summary"):
                alert["summary"] = alert["run_summary"]

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
        {"alerts": alerts, "active_page": "alerts"},
    )


@app.get("/admin", response_class=HTMLResponse, name="admin_panel")
def admin_panel(request: Request) -> HTMLResponse:
    """Renders the execution observability admin panel."""
    return templates.TemplateResponse(
        request,
        "admin.html",
        {"active_page": "admin"},
    )


@app.get("/api/admin/investigations")
def get_admin_investigations(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    alert_id: str = Query("", max_length=128),
):
    """Lists every investigation run, including failed and historical runs."""
    table_id = _agent_runs_table()
    query = f"""
    SELECT {_RUN_KEY_SQL} AS run_key, alert_id, campaign_id, run_number, recommendation, confidence,
      COALESCE(run_status, 'not_recorded') AS run_status,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S IST', run_time, 'Asia/Kolkata') AS run_time_ist,
      duration_ms,
      TO_JSON_STRING(JSON_REMOVE(execution_metrics, '$.model_calls')) AS metrics_json
    FROM `{table_id}`
    WHERE @alert_id = '' 
       OR STRPOS(LOWER(alert_id), LOWER(@alert_id)) > 0
       OR STRPOS(LOWER(COALESCE(campaign_id, '')), LOWER(@alert_id)) > 0
    ORDER BY run_time DESC, run_key DESC
    LIMIT @limit OFFSET @offset
    """
    params = [
        bigquery.ScalarQueryParameter("limit", "INT64", limit + 1),
        bigquery.ScalarQueryParameter("offset", "INT64", offset),
        bigquery.ScalarQueryParameter("alert_id", "STRING", alert_id.strip()),
    ]
    try:
        ensure_agent_runs_table()
        rows = execute_query(query, parameters=params)
    except Exception as exc:
        logger.warning(f"Could not load Admin Panel investigations from BigQuery ({exc}).")
        rows = []

    runs = []
    for row in rows[:limit]:
        run = dict(row)
        run["execution_metrics"] = _admin_json(run.pop("metrics_json", None), dict)
        runs.append(run)
    return {
        "investigations": runs,
        "next_offset": offset + limit if len(rows) > limit else None,
    }


@app.get("/api/admin/batch-averages")
def get_admin_batch_averages(limit: int = Query(100, ge=1, le=500)):
    """Returns average token usage and duration grouped by investigation batch."""
    table_id = _agent_runs_table()
    total_tokens = "SAFE_CAST(JSON_VALUE(execution_metrics, '$.token_totals.total_tokens') AS FLOAT64)"
    query = f"""
    SELECT
      batch_id,
      COUNT(*) AS investigation_count,
      COUNTIF({total_tokens} IS NOT NULL) AS token_sample_count,
      AVG({total_tokens}) AS avg_total_tokens,
      COUNTIF(duration_ms IS NOT NULL) AS duration_sample_count,
      AVG(duration_ms) AS avg_duration_ms
    FROM `{table_id}`
    GROUP BY batch_id
    ORDER BY MAX(run_time) DESC, batch_id DESC
    LIMIT @limit
    """
    try:
        ensure_agent_runs_table()
        rows = execute_query(
            query,
            parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)],
        )
    except Exception as exc:
        logger.warning(f"Could not load Admin Panel batch averages from BigQuery ({exc}).")
        rows = []
    return {"batches": [dict(row) for row in rows]}


@app.get("/api/admin/investigations/{run_key}")
def get_admin_investigation(run_key: str):
    """Returns per-model-request usage and per-tool timings for one run."""
    table_id = _agent_runs_table()
    query = f"""
    SELECT {_RUN_KEY_SQL} AS run_key, alert_id, campaign_id, run_number, recommendation, confidence,
      COALESCE(run_status, 'not_recorded') AS run_status,
      FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S IST', run_time, 'Asia/Kolkata') AS run_time_ist,
      duration_ms, TO_JSON_STRING(execution_metrics) AS metrics_json,
      TO_JSON_STRING(tool_calls) AS tool_calls_json
    FROM `{table_id}`
    WHERE {_RUN_KEY_SQL} = @run_key
    LIMIT 1
    """
    try:
        ensure_agent_runs_table()
        rows = execute_query(
            query, parameters=[bigquery.ScalarQueryParameter("run_key", "STRING", run_key)],
        )
    except Exception as exc:
        logger.exception(f"Could not load Admin Panel investigation {run_key}: {exc}")
        raise HTTPException(status_code=503, detail="Unable to load investigation metrics.")
    if not rows:
        raise HTTPException(status_code=404, detail="Investigation run not found.")
    run = dict(rows[0])
    run["execution_metrics"] = _admin_json(run.pop("metrics_json", None), dict)
    run["tool_calls"] = _admin_json(run.pop("tool_calls_json", None), list)
    return run


@app.get("/api/evidence/verify")
def verify_evidence_endpoint(
    ref: str = Query(..., min_length=1, max_length=256),
    campaign_id: Optional[str] = Query(None, max_length=128),
    merchant_id: Optional[str] = Query(None, max_length=128),
):
    """Resolves an evidence reference to underlying Bronze records for audit verification."""
    from services.evidence_service import EvidenceResolver
    resolver = EvidenceResolver()
    return resolver.resolve_evidence(
        evidence_ref=ref,
        campaign_id=campaign_id,
        merchant_id=merchant_id,
    )


@app.post("/alerts/{alert_id}/investigate", name="investigate_alert")
def investigate_alert(request: Request, alert_id: str) -> HTMLResponse:
    if not ALERT_ID_PATTERN.fullmatch(alert_id):
        return _render_error(request, "Invalid alert ID.", status_code=400)

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

        exec_id = report_data.get("execution_id") or result.get("execution_id") or f"exec_{alert_id}"
        report_data["execution_id"] = exec_id

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
    # Retrieve full investigation dossier directly from agent_runs table in BigQuery
    report = _fetch_agent_run_report(alert_id)

    if not report:
        return _render_error(
            request,
            "No saved investigation report exists for this alert in agent_runs.",
            status_code=404,
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

        if not tool_t and not thought_t and total_t > (prompt_t + cand_t):
            tool_t = total_t - (prompt_t + cand_t)
            metrics["tool_use_tokens"] = tool_t

        if "input_tokens" not in metrics:
            metrics["input_tokens"] = prompt_t + tool_t
        if "output_tokens" not in metrics:
            metrics["output_tokens"] = cand_t + thought_t

    tool_calls = report.get("tool_calls") or []
    execution_steps = _build_execution_steps(tool_calls)

    alert_row = None
    try:
        alert_row = _fetch_open_alert(alert_id)
    except Exception:
        pass

    # Ensure rule information is enriched for report view
    rule_id = (alert_row.get("rule_id") if alert_row else None) or report.get("rule_id")
    rule_info = RULE_DETAILS.get(str(rule_id), {})
    rule_name = rule_info.get("name", "Offer Optimization Alert")
    rule_meaning = rule_info.get("meaning", "Anomaly detected against campaign performance thresholds.")

    if alert_row:
        if not alert_row.get("rule_name"):
            alert_row["rule_name"] = rule_name
        if not alert_row.get("rule_meaning"):
            alert_row["rule_meaning"] = rule_meaning

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
            "rule_id": rule_id,
            "rule_name": rule_name,
            "rule_meaning": rule_meaning,
            "timeline": timeline,
            "active_page": "alerts",
        },
    )


@app.get("/reports/{alert_id}/markdown", response_class=PlainTextResponse, name="download_report_markdown")
def download_report_markdown(alert_id: str) -> PlainTextResponse:
    report_data = _fetch_agent_run_report(alert_id)
    if not report_data:
        raise HTTPException(status_code=404, detail="No saved investigation report exists for this alert.")

    try:
        res = convert_json_report_to_markdown(report_data=report_data, save_to_gcs=False)
        return PlainTextResponse(content=res.get("markdown_content", ""), media_type="text/markdown")
    except Exception as exc:
        logger.exception("Failed to render markdown report", extra={"alert_id": alert_id})
        raise HTTPException(status_code=500, detail="Could not render markdown report.")


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}
