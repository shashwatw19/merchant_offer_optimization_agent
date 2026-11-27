CREATE TABLE IF NOT EXISTS `offers_gold.rule_config` (
    rule_id STRING NOT NULL,
    parameter STRING NOT NULL,
    value NUMERIC NOT NULL,
    description STRING,
    updated_at TIMESTAMP,
    PRIMARY KEY (rule_id, parameter) NOT ENFORCED
);

MERGE `offers_gold.rule_config` T
USING (
    SELECT 'R1' AS rule_id, 'redemption_rate_min' AS parameter, 5.00 AS value, 'Minimum acceptable percentage of targeted audience customers who redeem cashback' AS description
    UNION ALL
    SELECT 'R2' AS rule_id, 'period_drop_pct' AS parameter, 50.00 AS value, 'Percentage drop between first-half baseline redemption rate and second-half runtime rate' AS description
    UNION ALL
    SELECT 'R2' AS rule_id, 'min_baseline_rate' AS parameter, 10.00 AS value, 'Minimum baseline redemption rate in Period 1 required to trigger velocity drop evaluation' AS description
    UNION ALL
    SELECT 'R3' AS rule_id, 'existing_customer_max' AS parameter, 75.00 AS value, 'Maximum allowable percentage of repeat customers in a new customer acquisition campaign' AS description
) S
ON T.rule_id = S.rule_id AND T.parameter = S.parameter
WHEN MATCHED THEN
    UPDATE SET value = S.value, description = S.description, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
    INSERT (rule_id, parameter, value, description, updated_at)
    VALUES (S.rule_id, S.parameter, S.value, S.description, CURRENT_TIMESTAMP());
