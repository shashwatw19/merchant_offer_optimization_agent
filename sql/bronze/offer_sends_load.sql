CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_offer_sends`
(
    send_id STRING,
    campaign_id STRING,
    customer_id STRING,
    sent_at STRING,
    delivery_status STRING,
    channel STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/offer_sends.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.offer_sends_raw`
(
    send_id STRING,
    campaign_id STRING,
    customer_id STRING,
    sent_at STRING,
    delivery_status STRING,
    channel STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.offer_sends_raw`
(
    send_id,
    campaign_id,
    customer_id,
    sent_at,
    delivery_status,
    channel,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(send_id AS STRING),
    CAST(campaign_id AS STRING),
    CAST(customer_id AS STRING),
    CAST(sent_at AS STRING),
    CAST(delivery_status AS STRING),
    CAST(channel AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_offer_sends`;