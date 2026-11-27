CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_transactions`
(
    txn_id STRING,
    customer_id STRING,
    merchant_id STRING,
    card_number STRING,
    account_number STRING,
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
    card_number STRING,
    account_number STRING,
    txn_ts STRING,
    amount STRING,
    txn_status STRING,
    batch_id STRING,
    ingestion_ts STRING,
    PRIMARY KEY (txn_id) NOT ENFORCED,
    CONSTRAINT fk_bronze_transactions_customer FOREIGN KEY (customer_id) REFERENCES `prj-imp-act-campaign.offers_bronze.customers_raw`(customer_id) NOT ENFORCED,
    CONSTRAINT fk_bronze_transactions_merchant FOREIGN KEY (merchant_id) REFERENCES `prj-imp-act-campaign.offers_bronze.merchants_raw`(merchant_id) NOT ENFORCED
);

ALTER TABLE `prj-imp-act-campaign.offers_bronze.transactions_raw`
ADD COLUMN IF NOT EXISTS card_number STRING,
ADD COLUMN IF NOT EXISTS account_number STRING;

INSERT INTO `prj-imp-act-campaign.offers_bronze.transactions_raw`
(
    txn_id,
    customer_id,
    merchant_id,
    card_number,
    account_number,
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
    CAST(card_number AS STRING),
    CAST(account_number AS STRING),
    CAST(txn_ts AS STRING),
    CAST(amount AS STRING),
    CAST(txn_status AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_transactions`;