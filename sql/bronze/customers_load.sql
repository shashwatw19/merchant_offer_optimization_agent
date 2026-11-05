CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_customers`
(
    customer_id STRING,
    city STRING,
    segment STRING,
    marketing_eligible STRING,
    card_status STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/customers.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.customers_raw`
(
    customer_id STRING,
    city STRING,
    segment STRING,
    marketing_eligible STRING,
    card_status STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.customers_raw`
(
    customer_id,
    city,
    segment,
    marketing_eligible,
    card_status,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(customer_id AS STRING),
    CAST(city AS STRING),
    CAST(segment AS STRING),
    CAST(marketing_eligible AS STRING),
    CAST(card_status AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_customers`;