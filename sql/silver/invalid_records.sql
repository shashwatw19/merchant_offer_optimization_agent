CREATE OR REPLACE TABLE `prj-imp-act-campaign.card_silver.invalid_records`
(
    table_name STRING NOT NULL,
    record_id STRING,
    reason STRING,
    raw_record JSON,
    batch_id STRING,
    rejected_at TIMESTAMP NOT NULL
)
OPTIONS (
    description = "Silver error quarantine table capturing records failing validation checks across raw ingestions"
);
