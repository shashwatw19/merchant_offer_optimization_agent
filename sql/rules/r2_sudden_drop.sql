-- Rule R2: Sudden Drop in Redemption Rate Between Comparable Periods
-- Parameters: min_p1_rate, drop_multiplier loaded from alert_rules_config
WITH rule_config AS (
    SELECT
        MAX(CASE WHEN parameter = 'min_p1_rate' THEN value END) AS min_p1_rate,
        MAX(CASE WHEN parameter = 'drop_multiplier' THEN value END) AS drop_multiplier
    FROM `{project}.{gold_dataset}.alert_rules_config`
    WHERE rule_id = 'R2'
),
campaign_txns AS (
    SELECT
        c.campaign_id,
        c.merchant_id,
        c.start_date,
        c.end_date,
        DATE_DIFF(c.end_date, c.start_date, DAY) / 2 AS mid_point_days,
        DATE_ADD(c.start_date, INTERVAL CAST(FLOOR(DATE_DIFF(c.end_date, c.start_date, DAY) / 2) AS INT64) DAY) AS mid_date,
        r.customer_id,
        r.awarded_at
    FROM `{project}.{silver_dataset}.campaigns` c
    JOIN `{project}.{silver_dataset}.offer_redemptions` r
        ON r.campaign_id = c.campaign_id
    WHERE UPPER(r.status) = 'AWARDED'
      AND c.status = 'ACTIVE'
),
sends AS (
    SELECT
        campaign_id,
        COUNT(DISTINCT customer_id) AS targeted_customers
    FROM `{project}.{silver_dataset}.offer_sends`
    GROUP BY campaign_id
),
period_metrics AS (
    SELECT
        ct.campaign_id,
        ct.merchant_id,
        s.targeted_customers,
        COUNT(DISTINCT CASE WHEN DATE(ct.awarded_at) <= ct.mid_date THEN ct.customer_id END) AS p1_redeemers,
        COUNT(DISTINCT CASE WHEN DATE(ct.awarded_at) > ct.mid_date THEN ct.customer_id END) AS p2_redeemers
    FROM campaign_txns ct
    JOIN sends s ON s.campaign_id = ct.campaign_id
    GROUP BY ct.campaign_id, ct.merchant_id, s.targeted_customers
),
period_rates AS (
    SELECT
        campaign_id,
        merchant_id,
        ROUND(SAFE_DIVIDE(p1_redeemers, targeted_customers) * 100, 2) AS p1_rate,
        ROUND(SAFE_DIVIDE(p2_redeemers, targeted_customers) * 100, 2) AS p2_rate
    FROM period_metrics
    WHERE targeted_customers > 0
)
SELECT
    pr.campaign_id,
    pr.merchant_id,
    'R2' AS rule_id,
    'period_redemption_drop_pct' AS metric_name,
    pr.p2_rate AS metric_value,
    ROUND(pr.p1_rate * COALESCE(cfg.drop_multiplier, 0.50), 2) AS threshold,
    'OPEN' AS status
FROM period_rates pr
LEFT JOIN rule_config cfg ON TRUE
WHERE pr.p1_rate >= COALESCE(cfg.min_p1_rate, 10.00)
  AND pr.p2_rate <= (pr.p1_rate * COALESCE(cfg.drop_multiplier, 0.50))
ORDER BY pr.campaign_id;

