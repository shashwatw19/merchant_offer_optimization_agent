-- ==============================================================================
-- 08_generate_alerts.sql
-- DIRECT ALERT GENERATION (Coupled with Gold Layer)
-- Evaluates R1, R2, R3 using parameters dynamically read from offers_gold.rule_config
-- ==============================================================================

CREATE TABLE IF NOT EXISTS `offers_gold.alerts` (
    alert_id STRING NOT NULL OPTIONS(description = 'Unique alert identifier'),
    campaign_id STRING NOT NULL OPTIONS(description = 'Underperforming campaign ID'),
    merchant_id STRING OPTIONS(description = 'Associated merchant identifier'),
    rule_id STRING NOT NULL OPTIONS(description = 'Triggered rule: R1, R2, or R3'),
    metric_name STRING OPTIONS(description = 'Violated metric parameter name'),
    metric_value NUMERIC OPTIONS(description = 'Observed metric value in current batch'),
    threshold_value NUMERIC OPTIONS(description = 'Configured threshold value evaluated against'),
    status STRING NOT NULL OPTIONS(description = 'Alert status: OPEN, PROCESSING, RESOLVED, ERROR'),
    created_at TIMESTAMP NOT NULL OPTIONS(description = 'Alert creation timestamp in IST'),
    resolved_at TIMESTAMP OPTIONS(description = 'Timestamp of resolution in IST'),
    summary STRING OPTIONS(description = 'Initial alert summary or findings'),
    investigation_summary STRING OPTIONS(description = 'AI agent synthesized resolution summary'),
    batch_id STRING OPTIONS(description = 'Batch token during which alert was generated')
);

INSERT INTO `offers_gold.alerts` (
    alert_id, campaign_id, merchant_id, rule_id, metric_name, metric_value,
    threshold_value, status, created_at, summary, batch_id
)
-- Query dynamic parameters from offers_gold.rule_config
WITH config_params AS (
    SELECT 
        MAX(CASE WHEN rule_id = 'R1' AND parameter = 'redemption_rate_min' THEN value END) AS r1_min_rate,
        MAX(CASE WHEN rule_id = 'R2' AND parameter = 'period_drop_pct' THEN value END) AS r2_drop_pct,
        MAX(CASE WHEN rule_id = 'R2' AND parameter = 'min_baseline_rate' THEN value END) AS r2_min_base,
        MAX(CASE WHEN rule_id = 'R3' AND parameter = 'existing_customer_max' THEN value END) AS r3_max_existing
    FROM `offers_gold.rule_config`
),

-- Rule 1: Low Redemption Rate (< r1_min_rate)
r1_candidates AS (
    SELECT
        gr.campaign_id,
        gr.merchant_id,
        'R1' AS rule_id,
        'redemption_rate' AS metric_name,
        ROUND(SAFE_DIVIDE(gr.redeeming_customer_count, NULLIF(gr.targeted_customer_count, 0)) * 100, 2) AS metric_value,
        cfg.r1_min_rate AS threshold_value,
        CONCAT('Redemption rate of ', CAST(ROUND(SAFE_DIVIDE(gr.redeeming_customer_count, NULLIF(gr.targeted_customer_count, 0)) * 100, 2) AS STRING), '% fell below the ', CAST(cfg.r1_min_rate AS STRING), '% threshold.') AS summary
    FROM `offers_gold.gold_campaign_results` gr
    CROSS JOIN config_params cfg
    WHERE gr.targeted_customer_count > 0
      AND SAFE_DIVIDE(gr.redeeming_customer_count, NULLIF(gr.targeted_customer_count, 0)) * 100 < cfg.r1_min_rate
),

-- Rule 2: Sudden Drop in Redemption Velocity (Period 1 vs Period 2)
campaign_windows AS (
    SELECT
        c.campaign_id,
        c.merchant_id,
        c.start_date,
        c.end_date,
        DATE_ADD(c.start_date, INTERVAL CAST(FLOOR(DATE_DIFF(c.end_date, c.start_date, DAY) / 2) AS INT64) DAY) AS mid_date,
        r.customer_id,
        r.awarded_at
    FROM `offers_silver.campaigns` c
    JOIN `offers_silver.offer_redemptions` r
      ON r.campaign_id = c.campaign_id
    WHERE UPPER(r.status) = 'AWARDED'
      AND UPPER(c.status) = 'ACTIVE'
),
window_metrics AS (
    SELECT
        cw.campaign_id,
        cw.merchant_id,
        COUNT(DISTINCT s.customer_id) AS targeted_customers,
        COUNT(DISTINCT CASE WHEN DATE(cw.awarded_at) <= cw.mid_date THEN cw.customer_id END) AS p1_redeemers,
        COUNT(DISTINCT CASE WHEN DATE(cw.awarded_at) > cw.mid_date THEN cw.customer_id END) AS p2_redeemers
    FROM campaign_windows cw
    JOIN `offers_silver.offer_sends` s ON s.campaign_id = cw.campaign_id
    GROUP BY cw.campaign_id, cw.merchant_id
),
r2_candidates AS (
    SELECT
        wm.campaign_id,
        wm.merchant_id,
        'R2' AS rule_id,
        'period_redemption_drop_pct' AS metric_name,
        ROUND(SAFE_DIVIDE(wm.p2_redeemers, wm.targeted_customers) * 100, 2) AS metric_value,
        ROUND(SAFE_DIVIDE(wm.p1_redeemers, wm.targeted_customers) * 100 * (1 - (cfg.r2_drop_pct / 100.0)), 2) AS threshold_value,
        CONCAT('Period 2 redemption rate dropped by more than ', CAST(cfg.r2_drop_pct AS STRING), '% relative to baseline Period 1.') AS summary
    FROM window_metrics wm
    CROSS JOIN config_params cfg
    WHERE wm.targeted_customers > 0
      AND (SAFE_DIVIDE(wm.p1_redeemers, wm.targeted_customers) * 100) >= cfg.r2_min_base
      AND (SAFE_DIVIDE(wm.p2_redeemers, wm.targeted_customers) * 100) <= (SAFE_DIVIDE(wm.p1_redeemers, wm.targeted_customers) * 100 * (1 - (cfg.r2_drop_pct / 100.0)))
),

-- Rule 3: Existing Customer Dominance in Acquisition Campaigns (>= r3_max_existing)
acquisition_customers AS (
    SELECT
        c.campaign_id,
        c.merchant_id,
        rr.customer_id,
        MAX(CASE WHEN CAST(tx.txn_ts AS DATETIME) < DATETIME(c.start_date) AND tx.merchant_id = c.merchant_id AND UPPER(tx.txn_status) = 'POSTED' THEN 1 ELSE 0 END) AS is_existing
    FROM `offers_silver.offer_redemptions` rr
    JOIN `offers_silver.campaigns` c ON c.campaign_id = rr.campaign_id
    LEFT JOIN `offers_silver.transactions` tx ON tx.customer_id = rr.customer_id AND tx.merchant_id = c.merchant_id
    WHERE UPPER(c.objective) = 'ACQUIRE_NEW'
      AND UPPER(rr.status) = 'AWARDED'
    GROUP BY c.campaign_id, c.merchant_id, rr.customer_id
),
r3_candidates AS (
    SELECT
        ac.campaign_id,
        ac.merchant_id,
        'R3' AS rule_id,
        'existing_customer_share_pct' AS metric_name,
        ROUND(SAFE_DIVIDE(COUNTIF(ac.is_existing = 1), COUNT(ac.customer_id)) * 100, 2) AS metric_value,
        cfg.r3_max_existing AS threshold_value,
        CONCAT('Existing customers accounted for ', CAST(ROUND(SAFE_DIVIDE(COUNTIF(ac.is_existing = 1), COUNT(ac.customer_id)) * 100, 2) AS STRING), '% of redemptions in new-customer acquisition campaign.') AS summary
    FROM acquisition_customers ac
    CROSS JOIN config_params cfg
    GROUP BY ac.campaign_id, ac.merchant_id, cfg.r3_max_existing
    HAVING metric_value >= cfg.r3_max_existing
),

all_new_candidates AS (
    SELECT * FROM r1_candidates
    UNION ALL
    SELECT * FROM r2_candidates
    UNION ALL
    SELECT * FROM r3_candidates
)

SELECT 
    CONCAT('ALT-', SUBSTR(TO_HEX(MD5(CONCAT(cand.rule_id, ':', cand.campaign_id))), 1, 8)) AS alert_id,
    cand.campaign_id,
    cand.merchant_id,
    cand.rule_id,
    cand.metric_name,
    CAST(cand.metric_value AS NUMERIC) AS metric_value,
    CAST(cand.threshold_value AS NUMERIC) AS threshold_value,
    'OPEN' AS status,
    CURRENT_TIMESTAMP() AS created_at,
    cand.summary,
    @batch_id AS batch_id
FROM all_new_candidates cand
WHERE NOT EXISTS (
    SELECT 1 FROM `offers_gold.alerts` existing
    WHERE existing.campaign_id = cand.campaign_id
      AND existing.rule_id = cand.rule_id
      AND existing.status IN ('OPEN', 'PROCESSING')
);
