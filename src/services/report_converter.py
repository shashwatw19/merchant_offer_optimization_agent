import json
from pathlib import Path
from typing import Any, Dict, Optional

from core.logging import logger
from services.gcs_storage import get_storage_service
from services.report_renderer import render_report_to_markdown


def convert_json_report_to_markdown(
    report_data: Optional[Dict[str, Any]] = None,
    json_path: Optional[str] = None,
    gcs_uri: Optional[str] = None,
    execution_id: Optional[str] = None,
    save_to_gcs: bool = True,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:

    storage = get_storage_service()
    raw_data: Optional[Dict[str, Any]] = None

    # Step 1: Resolve input JSON data
    try:
        if report_data is not None:
            raw_data = report_data
        elif gcs_uri is not None:
            logger.info(f"Retrieving JSON report from GCS: {gcs_uri}")
            raw_data = storage.download_json(gcs_uri)
        elif json_path is not None:
            local_p = Path(json_path)
            if not local_p.exists():
                return {
                    "success": False,
                    "error": f"Local JSON file not found: {json_path}",
                }
            with open(local_p, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        else:
            return {
                "success": False,
                "error": "One of 'report_data', 'json_path', or 'gcs_uri' must be provided.",
            }
    except Exception as exc:
        logger.error(f"Failed loading report data: {exc}")
        return {
            "success": False,
            "error": f"Failed loading report data: {exc}",
        }

    # Step 2: Extract identifiers
    alert_id = str(raw_data.get("alert_id", "UNKNOWN"))
    campaign_id = str(raw_data.get("campaign_id", "UNKNOWN"))
    effective_exec_id = execution_id or str(raw_data.get("execution_id") or f"exec_{alert_id}")

    # Step 3: Render Markdown deterministically
    try:
        markdown_text = render_report_to_markdown(
            report_data=raw_data,
            execution_id=effective_exec_id,
        )
    except Exception as exc:
        logger.error(f"Markdown rendering failed for alert {alert_id}: {exc}")
        return {
            "success": False,
            "alert_id": alert_id,
            "execution_id": effective_exec_id,
            "error": f"Markdown rendering failed: {exc}",
        }

    # Step 4: Persist locally if requested
    local_saved_path: Optional[str] = None
    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            f.write(markdown_text)
        local_saved_path = str(out_p)
        logger.info(f"Saved Markdown report locally to {local_saved_path}")

    # Step 5: Upload to GCS if requested
    gcs_result_uri: Optional[str] = None
    is_fallback = False
    if save_to_gcs:
        try:
            res = storage.upload_markdown(
                markdown_text=markdown_text,
                execution_id=effective_exec_id,
                alert_id=alert_id,
                campaign_id=campaign_id,
            )
            gcs_result_uri = res.uri
            is_fallback = res.is_fallback
            if not local_saved_path and res.local_path:
                local_saved_path = res.local_path
        except Exception as exc:
            logger.warning(f"Could not upload markdown to GCS: {exc}")

    return {
        "success": True,
        "execution_id": effective_exec_id,
        "alert_id": alert_id,
        "campaign_id": campaign_id,
        "markdown_content": markdown_text,
        "gcs_uri": gcs_result_uri,
        "local_path": local_saved_path,
        "is_fallback": is_fallback,
    }
