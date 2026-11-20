-- =====================================================================
-- 01_create_watermark_tables.sql
-- Ingestion Ledger & Watermark Control Tables for Incremental Pipeline
-- Dataset: offers_bronze (Matching New BFSI pattern: card_bronze.*)
-- =====================================================================

CREATE TABLE IF NOT EXISTS `offers_bronze.gcs_ingestion_log` (
    file_uri STRING NOT NULL OPTIONS(description = 'Full gs:// file URI of ingested blob'),
    file_name STRING OPTIONS(description = 'Base filename of the GCS object'),
    entity_type STRING OPTIONS(description = 'Identified entity type: campaigns, transactions, etc.'),
    file_etag STRING OPTIONS(description = 'MD5 hash / ETag of file for content change detection'),
    gcs_generation_id INT64 OPTIONS(description = 'Monotonic GCS object generation ID'),
    file_size_bytes INT64 OPTIONS(description = 'Blob size in bytes'),
    gcs_updated_time TIMESTAMP OPTIONS(description = 'GCS object updated_time in UTC'),
    batch_id STRING NOT NULL OPTIONS(description = 'Batch ID associated with this ingestion'),
    status STRING OPTIONS(description = 'Execution state: PENDING, INGESTED, SKIPPED, FAILED'),
    row_count INT64 OPTIONS(description = 'Number of raw records extracted into Bronze'),
    error_message STRING OPTIONS(description = 'Failure details if status is FAILED'),
    ingested_at TIMESTAMP NOT NULL OPTIONS(description = 'Timestamp of ingestion completion in IST')
)
PARTITION BY DATE(ingested_at)
OPTIONS (
    description = 'Audit and state-tracking ledger for GCS file arrivals to ensure strictly once, incremental ingestion'
);

CREATE TABLE IF NOT EXISTS `offers_bronze.pipeline_watermark` (
    entity_name STRING NOT NULL OPTIONS(description = 'Table or pipeline entity name'),
    last_batch_id STRING NOT NULL OPTIONS(description = 'Latest processed batch ID'),
    high_watermark TIMESTAMP OPTIONS(description = 'Latest processed source timestamp in IST'),
    cumulative_rows_bronze INT64 DEFAULT 0 OPTIONS(description = 'Total rows received in Bronze layer'),
    cumulative_rows_silver INT64 DEFAULT 0 OPTIONS(description = 'Total clean rows promoted to Silver layer'),
    cumulative_rows_rejected INT64 DEFAULT 0 OPTIONS(description = 'Total rows quarantined in rejected_records'),
    last_discrepancy_count INT64 DEFAULT 0 OPTIONS(description = 'Conservation discrepancy count (must be 0)'),
    last_updated TIMESTAMP NOT NULL OPTIONS(description = 'Last watermark update timestamp in IST'),
    PRIMARY KEY (entity_name) NOT ENFORCED
)
OPTIONS (
    description = 'Tracks high-watermarks, cumulative counts, and BR-4 conservation invariants across pipeline runs'
);
