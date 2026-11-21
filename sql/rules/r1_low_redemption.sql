-- ==============================================================================
-- Rule R1: Low Redemption Rate Alert (< redemption_rate_min % by default)
-- Parameter: redemption_rate_min loaded dynamically from {project}.{gold_dataset}.rule_config
-- Filter criterion: redemption_rate < threshold_val
-- ==============================================================================
WITH rule_param AS (
    SELECT COALESCE(
        (SELECT value FROM `{project}.{gold_dataset}.rule_config` WHERE rule_id = 'R1' AND parameter = 'redemption_rate_min' LIMIT 1),
        5.00
    ) AS threshold_val
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
    campaign_id,
    merchant_id,
    'R1' AS rule_id,
    'redemption_rate' AS metric_name,
    redemption_rate AS metric_value,
    p.threshold_val AS threshold,
    'OPEN' AS status
FROM campaign_fact
CROSS JOIN rule_param p
WHERE redemption_rate < p.threshold_val -- redemption_rate < 5.00
ORDER BY campaign_id;
