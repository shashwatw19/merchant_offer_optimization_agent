-- ==============================================================================
-- create_rule_config.sql
-- Table definition for dynamic rule parameter control table
-- ==============================================================================
CREATE TABLE IF NOT EXISTS `{project}.{gold_dataset}.rule_config` (
    rule_id STRING NOT NULL OPTIONS(description = 'Rule identifier: R1, R2, R3'),
    parameter STRING NOT NULL OPTIONS(description = 'Configurable parameter name'),
    value NUMERIC NOT NULL OPTIONS(description = 'Dynamic threshold numeric value'),
    description STRING OPTIONS(description = 'Human-readable description of parameter behavior'),
    updated_at TIMESTAMP OPTIONS(description = 'Timestamp of last parameter update')
);
