CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_transactions`
(
    txn_id STRING,
    customer_id STRING,
    merchant_id STRING,
    txn_ts STRING,
    amount STRING,
    txn_status STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/transactions.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.transactions_raw`
(
    txn_id STRING,
    customer_id STRING,
    merchant_id STRING,
    txn_ts STRING,
    amount STRING,
    txn_status STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.transactions_raw`
(
    txn_id,
    customer_id,
    merchant_id,
    txn_ts,
    amount,
    txn_status,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(txn_id AS STRING),
    CAST(customer_id AS STRING),
    CAST(merchant_id AS STRING),
    CAST(txn_ts AS STRING),
    CAST(amount AS STRING),
    CAST(txn_status AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_transactions`;