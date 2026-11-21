-- ==============================================================================
-- Rule R3: Dominance of Existing Customers in New-Customer Acquisition Campaigns
-- Parameter: existing_customer_max dynamically loaded from {project}.{gold_dataset}.rule_config
-- Filter criterion: existing_customer_share >= max_existing
-- ==============================================================================
WITH rule_param AS (
    SELECT COALESCE(
        (SELECT value FROM `{project}.{gold_dataset}.rule_config` WHERE rule_id = 'R3' AND parameter = 'existing_customer_max' LIMIT 1),
        75.00
    ) AS max_existing
),
redeeming_customers AS (
    SELECT
        c.campaign_id,
        c.merchant_id,
        rr.customer_id,
        MAX(
            CASE
                WHEN CAST(tx.txn_ts AS DATETIME) < DATETIME(c.start_date)
                 AND tx.merchant_id = c.merchant_id
                 AND UPPER(tx.txn_status) = 'POSTED'
                THEN 1
                ELSE 0
            END
        ) AS is_existing_customer
    FROM `{project}.{silver_dataset}.offer_redemptions` rr
    INNER JOIN `{project}.{silver_dataset}.campaigns` c
        ON c.campaign_id = rr.campaign_id
    LEFT JOIN `{project}.{silver_dataset}.transactions` tx
        ON tx.customer_id = rr.customer_id
       AND tx.merchant_id = c.merchant_id
       AND UPPER(tx.txn_status) = 'POSTED'
       AND CAST(tx.txn_ts AS DATETIME) < DATETIME(c.start_date)
    WHERE UPPER(c.objective) = 'ACQUIRE_NEW'
      AND UPPER(rr.status) = 'AWARDED'
    GROUP BY
        c.campaign_id,
        c.merchant_id,
        rr.customer_id
),
campaign_fact AS (
    SELECT
        campaign_id,
        merchant_id,
        COUNT(DISTINCT customer_id) AS redeeming_customers,
        COUNT(DISTINCT CASE WHEN is_existing_customer = 1 THEN customer_id END) AS existing_customer_redeemers,
        ROUND(
            SAFE_DIVIDE(
                COUNT(DISTINCT CASE WHEN is_existing_customer = 1 THEN customer_id END),
                COUNT(DISTINCT customer_id)
            ) * 100,
            2
        ) AS existing_customer_share
    FROM redeeming_customers
    GROUP BY
        campaign_id,
        merchant_id
)
SELECT
    campaign_id,
    merchant_id,
    'R3' AS rule_id,
    'existing_customer_share_pct' AS metric_name,
    existing_customer_share AS metric_value,
    p.max_existing AS threshold,
    'OPEN' AS status
FROM campaign_fact
CROSS JOIN rule_param p
WHERE existing_customer_share >= p.max_existing -- existing_customer_share >= 75.00
ORDER BY campaign_id;
