-- Rule R3: Low Acquisition Alert (Existing customer dominance >= 75% in new acquisition campaigns)
-- Parameter: existing_customer_share_threshold loaded from alert_rules_config
-- Filter criterion: existing_customer_share >= 75.00
WITH rule_config AS (
    SELECT value AS threshold
    FROM `{project}.{gold_dataset}.alert_rules_config`
    WHERE rule_id = 'R3' AND parameter = 'existing_customer_share_threshold'
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
    f.campaign_id,
    f.merchant_id,
    'R3' AS rule_id,
    'existing_customer_share_pct' AS metric_name,
    f.existing_customer_share AS metric_value,
    COALESCE(cfg.threshold, 75.00) AS threshold,
    'OPEN' AS status
FROM campaign_fact f
LEFT JOIN rule_config cfg ON TRUE
WHERE f.existing_customer_share >= COALESCE(cfg.threshold, 75.00)
ORDER BY f.campaign_id;

