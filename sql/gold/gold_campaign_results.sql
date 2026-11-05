CREATE OR REPLACE TABLE `prj-imp-act-campaign.offers_gold.gold_campaign_results` AS

WITH campaign_base AS (

    SELECT
        campaign_id,
        merchant_id,

        DATETIME(CAST(start_date AS DATE)) AS measurement_start_date,

        DATETIME(
            CAST(end_date AS DATE),
            TIME '23:59:59'
        ) AS measurement_end_date,

        batch_id,

        COALESCE(status, 'UNKNOWN') AS campaign_status,

        CASE
            WHEN SAFE_CAST(max_redemptions_per_customer AS INT64) > 0
            THEN SAFE_CAST(max_redemptions_per_customer AS INT64)
            ELSE 1
        END AS corrected_max_redemptions_per_customer

    FROM `prj-imp-act-campaign.offers_silver.campaigns`
),

sent_summary AS (

    SELECT
        campaign_id,

        COUNT(DISTINCT customer_id) AS targeted_customer_count,

        COUNT(
            DISTINCT CASE
                WHEN UPPER(delivery_status) = 'DELIVERED'
                THEN customer_id
            END
        ) AS delivered_customer_count

    FROM `prj-imp-act-campaign.offers_silver.offer_sends`

    GROUP BY campaign_id
),

redemption_summary AS (

    SELECT
        campaign_id,

        COUNT(DISTINCT customer_id) AS redeeming_customer_count,

        ROUND(
            SUM(
                CASE
                    WHEN UPPER(status) = 'AWARDED'
                    THEN awarded_cashback
                    ELSE 0
                END
            ),
            2
        ) AS cashback_amt_awarded

    FROM `prj-imp-act-campaign.offers_silver.offer_redemptions`
    WHERE UPPER(status) = 'AWARDED'

    GROUP BY campaign_id
),

txn_summary AS (

    SELECT
        r.campaign_id,

        COUNT(DISTINCT t.txn_id) AS posted_txn_count,

        ROUND(
            SUM(t.amount),
            2
        ) AS posted_txn_amount

    FROM `prj-imp-act-campaign.offers_silver.transactions` t

    INNER JOIN `prj-imp-act-campaign.offers_silver.offer_redemptions` r
        ON t.txn_id = r.txn_id

    WHERE UPPER(t.txn_status) = 'POSTED'

    GROUP BY r.campaign_id
)

SELECT
    cb.campaign_id,
    cb.merchant_id,
    cb.measurement_start_date,
    cb.measurement_end_date,
   
    COALESCE(ss.targeted_customer_count, 0) AS targeted_customer_count,

    COALESCE(ss.delivered_customer_count, 0) AS delivered_customer_count,

    COALESCE(rs.redeeming_customer_count, 0) AS redeeming_customer_count,

    ROUND(
        SAFE_DIVIDE(
            COALESCE(rs.redeeming_customer_count, 0),
            NULLIF(COALESCE(ss.targeted_customer_count, 0), 0)
        ) * 100,
        2
    ) AS redemption_rate_pct,

    ROUND(
        COALESCE(rs.cashback_amt_awarded, 0),
        2
    ) AS cashback_amt_awarded,

    COALESCE(ts.posted_txn_count, 0) AS posted_txn_count,

    ROUND(
        COALESCE(ts.posted_txn_amount, 0),
        2
    ) AS posted_txn_amount,

    cb.batch_id,

    DATETIME(CURRENT_TIMESTAMP(), 'Asia/Kolkata') AS ingestion_time,

    CASE
        WHEN cb.campaign_status = 'UNKNOWN'
             OR cb.corrected_max_redemptions_per_customer IS NULL
        THEN 'QUALITY_ISSUE'
        ELSE 'OK'
    END AS quality_flag

FROM campaign_base cb

LEFT JOIN sent_summary ss
    ON cb.campaign_id = ss.campaign_id

LEFT JOIN redemption_summary rs
    ON cb.campaign_id = rs.campaign_id

LEFT JOIN txn_summary ts
    ON cb.campaign_id = ts.campaign_id;
