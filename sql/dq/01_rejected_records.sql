-- =====================================================================
-- 01_rejected_records.sql
-- Description: Standalone DDL for offers_silver.invalid_records quarantine table (BR-4)
-- Formula: Holds unlinked, corrupt, or invalid rows across all Bronze entities
-- Dataset: offers_silver (Matching New BFSI pattern: card_silver.rejected_records)
-- =====================================================================

CREATE TABLE IF NOT EXISTS `offers_silver.invalid_records` (
    table_name STRING NOT NULL OPTIONS(description = 'Source entity name that generated the rejection'),
    record_id STRING OPTIONS(description = 'Entity primary key value or UNKNOWN if missing/blank'),
    reason STRING NOT NULL OPTIONS(description = 'Reason code for quarantine'),
    raw_record STRING NOT NULL OPTIONS(description = 'Full JSON serialized copy of the failed bronze record for audit and replay'),
    batch_id STRING NOT NULL OPTIONS(description = 'Batch load identifier when the record failed validation'),
    rejected_at TIMESTAMP NOT NULL OPTIONS(description = 'Timestamp in Indian Standard Time (Asia/Kolkata) when record was quarantined')
)
OPTIONS (
    description = 'Quarantine table storing invalid, corrupt, or unlinked records rejected during Silver layer transformations'
);
