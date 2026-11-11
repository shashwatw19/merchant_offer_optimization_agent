CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_campaigns`
(
  campaign_id STRING,
  merchant_id STRING,
  objective STRING,
  start_date STRING,
  end_date STRING,
  min_spend STRING,
  cashback_pct STRING,
  cashback_cap STRING,
  budget STRING,
  funding_type STRING,
  max_redemptions_per_customer STRING,
  status STRING
)
OPTIONS (
  format = 'CSV',
  skip_leading_rows = 1,
  uris = ['gs://prj-imp-act-campaign-data/raw_data/campaigns.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.campaigns_raw`
(
  campaign_id STRING,
  merchant_id STRING,
  objective STRING,
  start_date STRING,
  end_date STRING,
  min_spend STRING,
  cashback_pct STRING,
  cashback_cap STRING,
  budget STRING,
  funding_type STRING,
  max_redemptions_per_customer STRING,
  status STRING,
  batch_id STRING,
  ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.campaigns_raw`
SELECT
  CAST(campaign_id AS STRING),
  CAST(merchant_id AS STRING),
  CAST(objective AS STRING),
  CAST(start_date AS STRING),
  CAST(end_date AS STRING),
  CAST(min_spend AS STRING),
  CAST(cashback_pct AS STRING),
  CAST(cashback_cap AS STRING),
  CAST(budget AS STRING),
  CAST(funding_type AS STRING),
  CAST(max_redemptions_per_customer AS STRING),
  CAST(status AS STRING),
  @batch_id,
  @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_campaigns`;