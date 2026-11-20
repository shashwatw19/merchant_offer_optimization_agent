"""High-watermark state tracking and monotonic batch generation."""
from datetime import datetime, timezone, timedelta
from typing import Dict, Any
from core.bigquery_client import execute_query
from core.config import get_config
from core.logging import logger

IST = timezone(timedelta(hours=5, minutes=30))

class WatermarkService:
    """Manages incremental watermarks and monotonic batch IDs."""

    def __init__(self):
        self.config = get_config()
        self.project_id = self.config.gcp.project_id

    def generate_batch_id(self) -> str:
        """Generate a monotonic IST batch token: B_YYMMDD_HHMM."""
        return datetime.now(IST).strftime("B_%y%m%d_%H%M")

    def get_watermark(self, entity_name: str) -> Dict[str, Any]:
        """Fetch current high watermark for an entity."""
        table_id = f"{self.project_id}.offers_bronze.pipeline_watermark"
        sql = f"""
        SELECT entity_name, last_batch_id, high_watermark,
               cumulative_rows_bronze, cumulative_rows_silver, cumulative_rows_rejected
        FROM `{table_id}`
        WHERE entity_name = @entity
        LIMIT 1
        """
        from google.cloud import bigquery
        params = [bigquery.ScalarQueryParameter("entity", "STRING", entity_name)]
        try:
            rows = execute_query(sql, parameters=params)
            return rows[0] if rows else {}
        except Exception as exc:
            logger.warning(f"Could not read watermark for {entity_name}: {exc}")
            return {}
