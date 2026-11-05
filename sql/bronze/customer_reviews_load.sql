CREATE OR REPLACE EXTERNAL TABLE `prj-imp-act-campaign.offers_bronze.ext_customer_reviews`
(
    review_id STRING,
    merchant_id STRING,
    review_date STRING,
    collected_at STRING,
    rating STRING,
    review_text STRING,
    source_ref STRING
)
OPTIONS (
    format = 'CSV',
    skip_leading_rows = 1,
    uris = ['gs://prj-imp-act-campaign-data/raw_data/customer_reviews.csv']
);

CREATE TABLE IF NOT EXISTS `prj-imp-act-campaign.offers_bronze.customer_reviews_raw`
(
    review_id STRING,
    merchant_id STRING,
    review_date STRING,
    collected_at STRING,
    rating STRING,
    review_text STRING,
    source_ref STRING,
    batch_id STRING,
    ingestion_ts STRING
);

INSERT INTO `prj-imp-act-campaign.offers_bronze.customer_reviews_raw`
(
    review_id,
    merchant_id,
    review_date,
    collected_at,
    rating,
    review_text,
    source_ref,
    batch_id,
    ingestion_ts
)
SELECT
    CAST(review_id AS STRING),
    CAST(merchant_id AS STRING),
    CAST(review_date AS STRING),
    CAST(collected_at AS STRING),
    CAST(rating AS STRING),
    CAST(review_text AS STRING),
    CAST(source_ref AS STRING),
    @batch_id,
    @ingestion_ts
FROM `prj-imp-act-campaign.offers_bronze.ext_customer_reviews`;