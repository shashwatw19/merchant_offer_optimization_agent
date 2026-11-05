CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_merchant_feedback`
(
    feedback_id STRING,
    merchant_id STRING,
    event_date STRING,
    recorded_at STRING,
    feedback_text STRING,
    source_ref STRING,
    verification_status STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/merchant_feedback.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.merchant_feedback_raw`
(
    feedback_id STRING,
    merchant_id STRING,
    event_date STRING,
    recorded_at STRING,
    feedback_text STRING,
    source_ref STRING,
    verification_status STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.merchant_feedback_raw`
(
    feedback_id,
    merchant_id,
    event_date,
    recorded_at,
    feedback_text,
    source_ref,
    verification_status,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(feedback_id AS STRING),
    CAST(merchant_id AS STRING),
    CAST(event_date AS STRING),
    CAST(recorded_at AS STRING),
    CAST(feedback_text AS STRING),
    CAST(source_ref AS STRING),
    CAST(verification_status AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_merchant_feedback`;
