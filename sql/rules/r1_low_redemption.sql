-- Rule R1: Low Redemption Rate Alert (< 5% of targeted customer audience by default)
-- Parameter: redemption_rate_threshold loaded from alert_rules_config
-- Filter criterion: redemption_rate < 5.00
WITH rule_config AS (
    SELECT value AS threshold
    FROM `{project}.{gold_dataset}.alert_rules_config`
    WHERE rule_id = 'R1' AND parameter = 'redemption_rate_threshold'
),
campaign_fact AS (
    SELECT
        campaign_id,
        merchant_id,
        ROUND(
            SAFE_DIVIDE(
                redeeming_customer_count,
                NULLIF(targeted_customer_count, 0)
            ) * 100,
            2
        ) AS redemption_rate
    FROM `{project}.{gold_dataset}.gold_campaign_results`
    WHERE targeted_customer_count > 0
)
SELECT
    f.campaign_id,
    f.merchant_id,
    'R1' AS rule_id,
    'redemption_rate' AS metric_name,
    f.redemption_rate AS metric_value,
    COALESCE(cfg.threshold, 5.00) AS threshold,
    'OPEN' AS status
FROM campaign_fact f
LEFT JOIN rule_config cfg ON TRUE
WHERE f.redemption_rate < COALESCE(cfg.threshold, 5.00)
ORDER BY f.campaign_id;

