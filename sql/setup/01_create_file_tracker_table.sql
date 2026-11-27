-- =====================================================================
-- 01_create_file_tracker_table.sql
-- Tracks the latest loaded CSV file timestamp per entity folder in GCS
-- =====================================================================

CREATE TABLE IF NOT EXISTS `offers_bronze.file_load_tracker` (
    entity_name STRING NOT NULL OPTIONS(description = 'Entity folder / Bronze table name (e.g. merchants, transactions)'),
    last_loaded_file STRING OPTIONS(description = 'Full gs:// URI of the latest loaded CSV file'),
    last_file_timestamp TIMESTAMP NOT NULL OPTIONS(description = 'Timestamp of the latest loaded CSV file'),
    last_batch_id STRING NOT NULL OPTIONS(description = 'Batch ID of the last load'),
    rows_loaded INT64 DEFAULT 0 OPTIONS(description = 'Rows loaded in the last run'),
    updated_at TIMESTAMP NOT NULL OPTIONS(description = 'Timestamp when tracker was updated'),
    PRIMARY KEY (entity_name) NOT ENFORCED
)
OPTIONS (
    description = 'Stores the latest loaded CSV file timestamp per entity folder for Bronze ingestion'
);
