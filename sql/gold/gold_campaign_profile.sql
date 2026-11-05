CREATE OR REPLACE TABLE `prj-imp-act-campaign.offers_gold.gold_campaign_profile` AS

WITH campaign_profile_base AS (

    SELECT
        c.campaign_id,
        c.merchant_id,

        m.name AS merchant_name,
        m.category AS merchant_category,
        m.city AS merchant_city,

        c.objective,

        DATETIME(CAST(c.start_date AS DATE)) AS cmp_start_date,

        DATETIME(
            CAST(c.end_date AS DATE),
            TIME '23:59:59'
        ) AS cmp_end_date,

        ROUND(c.min_spend, 2) AS min_spend,
        ROUND(c.cashback_pct, 2) AS cashback_pct,
        ROUND(c.cashback_cap, 2) AS cashback_cap,
        ROUND(c.budget, 2) AS budget,

        c.funding_type,

        c.batch_id,

        CASE
            WHEN SAFE_CAST(c.max_redemptions_per_customer AS INT64) IS NOT NULL
                 AND SAFE_CAST(c.max_redemptions_per_customer AS INT64) > 0
            THEN SAFE_CAST(c.max_redemptions_per_customer AS INT64)
            ELSE 1
        END AS max_redemptions_per_customer,

        COALESCE(c.status, 'UNKNOWN') AS campaign_status --- unknown return karo agr status me kuch naa ho toh

    FROM `prj-imp-act-campaign.offers_silver.campaigns` c

    LEFT JOIN `prj-imp-act-campaign.offers_silver.merchants` m
        ON m.merchant_id = c.merchant_id
)

SELECT
    cp.campaign_id,
    cp.merchant_id,

    cp.merchant_name,
    cp.merchant_category,
    cp.merchant_city,
    cp.objective,
    cp.cmp_start_date
    cp.cmp_end_date
    cp.min_spend,
    cp.cashback_pct,
    cp.cashback_cap,
    cp.budget,
    cp.funding_type,
    cp.max_redemptions_per_customer,
    cp.campaign_status,
    cp.batch_id,


    DATETIME(CURRENT_TIMESTAMP(), 'Asia/Kolkata')AS ingestion_time,

    CASE
        WHEN cp.merchant_name IS NULL
          OR cp.merchant_category IS NULL
          OR cp.campaign_status = 'UNKNOWN'
        THEN 'QUALITY_ISSUE'
        ELSE 'OK'
    END AS quality_flag

FROM campaign_profile_base cp;