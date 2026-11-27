CREATE OR REPLACE TABLE `prj-imp-act-campaign.offers_gold.gold_merchant_spend_profile` (
    merchant_id STRING NOT NULL,
    merchant_name STRING,
    merchant_category STRING,
    merchant_city STRING,
    period_start DATETIME,
    period_end DATETIME,
    posted_txn_count INT64,
    posted_amount_total NUMERIC,
    avg_txn_amount NUMERIC,
    median_txn_amount NUMERIC,
    distinct_customer_count INT64,
    batch_id STRING,
    ingestion_time DATETIME,
    quality_flag STRING,
    PRIMARY KEY (merchant_id) NOT ENFORCED,
    CONSTRAINT fk_gold_merchant_spend_merchant FOREIGN KEY (merchant_id) REFERENCES `prj-imp-act-campaign.offers_silver.merchants`(merchant_id) NOT ENFORCED
);

INSERT INTO `prj-imp-act-campaign.offers_gold.gold_merchant_spend_profile` (
    merchant_id,
    merchant_name,
    merchant_category,
    merchant_city,
    period_start,
    period_end,
    posted_txn_count,
    posted_amount_total,
    avg_txn_amount,
    median_txn_amount,
    distinct_customer_count,
    batch_id,
    ingestion_time,
    quality_flag
)

WITH merchant_txn AS (

    SELECT
        m.merchant_id,
        m.name AS merchant_name,
        m.category AS merchant_category,
        m.city AS merchant_city,

        MAX(m.batch_id) AS batch_id,

        DATETIME(DATE_TRUNC(CURRENT_DATE(), MONTH)) AS period_start,

        DATETIME(
            LAST_DAY(CURRENT_DATE(), MONTH),
            TIME '23:59:59'
        ) AS period_end,

        COUNT(
            DISTINCT CASE
                WHEN UPPER(t.txn_status) = 'POSTED'
                THEN t.txn_id
            END
        ) AS posted_txn_count,

        ROUND(
            SUM(
                CASE
                    WHEN UPPER(t.txn_status) = 'POSTED'
                    THEN t.amount
                    ELSE 0
                END
            ),
            2
        ) AS posted_amount_total,

        ROUND(
            AVG(
                CASE
                    WHEN UPPER(t.txn_status) = 'POSTED'
                    THEN t.amount
                END
            ),
            2
        ) AS avg_txn_amount,

        ROUND(
            APPROX_QUANTILES(
                CASE
                    WHEN UPPER(t.txn_status) = 'POSTED'
                    THEN t.amount
                END,
                100
            )[OFFSET(50)],
            2
        ) AS median_txn_amount,

        COUNT(
            DISTINCT CASE
                WHEN UPPER(t.txn_status) = 'POSTED'
                THEN t.customer_id
            END
        ) AS distinct_customer_count

    FROM `prj-imp-act-campaign.offers_silver.merchants` m

    LEFT JOIN `prj-imp-act-campaign.offers_silver.transactions` t
        ON t.merchant_id = m.merchant_id

    GROUP BY
        m.merchant_id,
        m.name,
        m.category,
        m.city
)

SELECT
    mt.merchant_id,
    mt.merchant_name,
    mt.merchant_category,
    mt.merchant_city,
    mt.period_start,
    mt.period_end,
   
    COALESCE(mt.posted_txn_count, 0) AS posted_txn_count,

    COALESCE(mt.posted_amount_total, 0) AS posted_amount_total,

    COALESCE(mt.avg_txn_amount, 0) AS avg_txn_amount,

    COALESCE(mt.median_txn_amount, 0) AS median_txn_amount,

    COALESCE(mt.distinct_customer_count, 0) AS distinct_customer_count,

    mt.batch_id,
 
    DATETIME(CURRENT_TIMESTAMP(), 'Asia/Kolkata') AS ingestion_time,

    CASE
        WHEN mt.merchant_name IS NULL
          OR mt.merchant_category IS NULL
          OR mt.merchant_city IS NULL
        THEN 'QUALITY_ISSUE'
        ELSE 'OK'
    END AS quality_flag

FROM merchant_txn mt;
