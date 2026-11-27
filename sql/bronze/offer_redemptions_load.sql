CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_offer_redemptions`
(
    redemption_id STRING,
    txn_id STRING,
    campaign_id STRING,
    customer_id STRING,
    awarded_cashback STRING,
    status STRING,
    awarded_at STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/offer_redemptions.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.offer_redemptions_raw`
(
    redemption_id STRING,
    txn_id STRING,
    campaign_id STRING,
    customer_id STRING,
    awarded_cashback STRING,
    status STRING,
    awarded_at STRING,
    batch_id STRING,
    ingestion_ts STRING,
    PRIMARY KEY (redemption_id) NOT ENFORCED,
    CONSTRAINT fk_bronze_offer_redemptions_txn FOREIGN KEY (txn_id) REFERENCES `prj-imp-act-campaign.offers_bronze.transactions_raw`(txn_id) NOT ENFORCED,
    CONSTRAINT fk_bronze_offer_redemptions_campaign FOREIGN KEY (campaign_id) REFERENCES `prj-imp-act-campaign.offers_bronze.campaigns_raw`(campaign_id) NOT ENFORCED,
    CONSTRAINT fk_bronze_offer_redemptions_customer FOREIGN KEY (customer_id) REFERENCES `prj-imp-act-campaign.offers_bronze.customers_raw`(customer_id) NOT ENFORCED
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.offer_redemptions_raw`
(
    redemption_id,
    txn_id,
    campaign_id,
    customer_id,
    awarded_cashback,
    status,
    awarded_at,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(redemption_id AS STRING),
    CAST(txn_id AS STRING),
    CAST(campaign_id AS STRING),
    CAST(customer_id AS STRING),
    CAST(awarded_cashback AS STRING),
    CAST(status AS STRING),
    CAST(awarded_at AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_offer_redemptions`;