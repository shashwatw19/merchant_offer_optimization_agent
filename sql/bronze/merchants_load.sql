CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_merchants`
(
    merchant_id STRING,
    name STRING,
    category STRING,
    city STRING,
    status STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/merchants.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.merchants_raw`
(
    merchant_id STRING,
    name STRING,
    category STRING,
    city STRING,
    status STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.merchants_raw`
(
    merchant_id,
    name,
    category,
    city,
    status,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(merchant_id AS STRING),
    CAST(name AS STRING),
    CAST(category AS STRING),
    CAST(city AS STRING),
    CAST(status AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_merchants`;