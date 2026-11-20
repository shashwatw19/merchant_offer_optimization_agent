"""Syncs config/rule_config.csv into offers_gold.rule_config BigQuery table."""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure src/ is on python path if script is invoked as python sql/gold/load_rule_config.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from google.cloud import bigquery
from core.bigquery_client import get_bigquery_client
from core.config import get_config
from core.logging import logger

def load_rule_config(csv_path: str = "config/rule_config.csv", batch_id: str = "B_DEFAULT"):
    config = get_config()
    client = get_bigquery_client()
    table_id = f"{config.gcp.project_id}.{config.gcp.gold_dataset}.rule_config"
    
    file_path = Path(csv_path)
    if not file_path.is_file():
        logger.error(f"Rule config file not found at: {csv_path}")
        return False
        
    rows_to_insert = []
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows_to_insert.append({
                "rule_id": r["rule_id"],
                "parameter": r["parameter"],
                "value": float(r["value"]),
                "description": r["description"],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            
    if not rows_to_insert:
        logger.warning("No rows found in rule_config.csv")
        return False
        
    # Create table if not exists
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS `{table_id}` (
        rule_id STRING NOT NULL,
        parameter STRING NOT NULL,
        value NUMERIC NOT NULL,
        description STRING,
        updated_at TIMESTAMP
    )
    """
    client.query(create_sql).result()
    
    # Overwrite / Sync current configuration values
    truncate_sql = f"TRUNCATE TABLE `{table_id}`"
    client.query(truncate_sql).result()
    
    errors = client.insert_rows_json(table_id, rows_to_insert)
    if errors:
        logger.error(f"Failed to insert rule config rows: {errors}")
        return False
        
    logger.info(f"Successfully loaded {len(rows_to_insert)} rule parameters into `{table_id}` (Batch: {batch_id})")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load rule_config.csv to BigQuery")
    parser.add_argument("--csv_path", default="config/rule_config.csv")
    parser.add_argument("--batch_id", default="B_MANUAL")
    args = parser.parse_args()
    load_rule_config(args.csv_path, args.batch_id)
