CREATE OR REPLACE VIEW `offers_gold.v_conservation_audit` AS
WITH bronze_counts AS (
    SELECT 'campaigns' AS entity, COUNT(*) AS bronze_rows FROM `offers_bronze.campaigns_raw`
    UNION ALL
    SELECT 'transactions' AS entity, COUNT(*) AS bronze_rows FROM `offers_bronze.transactions_raw`
    UNION ALL
    SELECT 'customers' AS entity, COUNT(*) AS bronze_rows FROM `offers_bronze.customers_raw`
    UNION ALL
    SELECT 'merchants' AS entity, COUNT(*) AS bronze_rows FROM `offers_bronze.merchants_raw`
),
silver_counts AS (
    SELECT 'campaigns' AS entity, COUNT(*) AS silver_rows FROM `offers_silver.campaigns`
    UNION ALL
    SELECT 'transactions' AS entity, COUNT(*) AS silver_rows FROM `offers_silver.transactions`
    UNION ALL
    SELECT 'customers' AS entity, COUNT(*) AS silver_rows FROM `offers_silver.customers`
    UNION ALL
    SELECT 'merchants' AS entity, COUNT(*) AS silver_rows FROM `offers_silver.merchants`
),
rejected_counts AS (
    SELECT 
        REGEXP_EXTRACT(table_name, r'([a-z_]+)(?:_raw)?$') AS entity,
        COUNT(*) AS rejected_rows
    FROM `offers_silver.invalid_records`
    GROUP BY 1
)
SELECT 
    b.entity,
    b.bronze_rows,
    COALESCE(s.silver_rows, 0) AS silver_rows,
    COALESCE(r.rejected_rows, 0) AS rejected_rows,
    b.bronze_rows - (COALESCE(s.silver_rows, 0) + COALESCE(r.rejected_rows, 0)) AS discrepancy,
    CASE 
        WHEN b.bronze_rows - (COALESCE(s.silver_rows, 0) + COALESCE(r.rejected_rows, 0)) = 0 
        THEN 'CONSERVED' 
        ELSE 'AUDIT_DISCREPANCY' 
    END AS conservation_status
FROM bronze_counts b
LEFT JOIN silver_counts s ON b.entity = s.entity
LEFT JOIN rejected_counts r ON b.entity = r.entity;
