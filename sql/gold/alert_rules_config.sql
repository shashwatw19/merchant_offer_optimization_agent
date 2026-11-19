CREATE OR REPLACE TABLE `prj-imp-act-campaign.card_gold.alert_rules_config` AS

SELECT
    'R1' AS rule_id,
    'redemption_rate_threshold' AS parameter,
    5.00 AS value,
    'Maximum redemption rate percentage to trigger alert' AS description
UNION ALL
SELECT
    'R2' AS rule_id,
    'min_p1_rate' AS parameter,
    10.00 AS value,
    'Minimum period 1 redemption rate to qualify for drop check' AS description
UNION ALL
SELECT
    'R2' AS rule_id,
    'drop_multiplier' AS parameter,
    0.50 AS value,
    'Drop threshold multiplier comparing period 2 vs period 1' AS description
UNION ALL
SELECT
    'R3' AS rule_id,
    'existing_customer_share_threshold' AS parameter,
    75.00 AS value,
    'Minimum existing customer share percentage in acquisition campaigns' AS description;

