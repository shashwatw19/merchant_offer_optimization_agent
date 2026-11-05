/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.campaigns_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.campaigns

   CHANGES
   -------
   1. batch_id carried from Bronze
   2. Bronze ingestion_ts ignored
   3. Silver ingested_at generated in IST
========================================================== */


/* ==========================================================
   1. SILVER TABLE
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_silver.campaigns`
(
  campaign_id STRING NOT NULL,
  merchant_id STRING NOT NULL,
  objective STRING,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  min_spend NUMERIC,
  cashback_pct NUMERIC,
  cashback_cap NUMERIC,
  budget NUMERIC,
  funding_type STRING,
  max_redemptions_per_customer INT64,
  status STRING,

  batch_id STRING,

  ingested_at DATETIME NOT NULL
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_campaigns AS

WITH raw_data AS (

    SELECT

        TRIM(r.campaign_id) AS campaign_id,

        TRIM(r.merchant_id) AS merchant_id,

        r.batch_id AS batch_id,

        UPPER(TRIM(r.objective)) AS objective,

        COALESCE(
            SAFE.PARSE_DATE('%Y-%m-%d', TRIM(r.start_date)),
            SAFE.PARSE_DATE('%d-%m-%Y', TRIM(r.start_date)),
            SAFE.PARSE_DATE('%m/%d/%Y', TRIM(r.start_date)),
            SAFE_CAST(TRIM(r.start_date) AS DATE)
        ) AS parsed_start_date,

        COALESCE(
            SAFE.PARSE_DATE('%Y-%m-%d', TRIM(r.end_date)),
            SAFE.PARSE_DATE('%d-%m-%Y', TRIM(r.end_date)),
            SAFE.PARSE_DATE('%m/%d/%Y', TRIM(r.end_date)),
            SAFE_CAST(TRIM(r.end_date) AS DATE)
        ) AS parsed_end_date,

        SAFE_CAST(
            REGEXP_REPLACE(r.min_spend, r'[^\d.]', '')
            AS NUMERIC
        ) AS parsed_min_spend,

        SAFE_CAST(
            REGEXP_REPLACE(r.cashback_pct, r'[^\d.]', '')
            AS NUMERIC
        ) AS parsed_cashback_pct,

        SAFE_CAST(
            REGEXP_REPLACE(r.cashback_cap, r'[^\d.]', '')
            AS NUMERIC
        ) AS parsed_cashback_cap,

        SAFE_CAST(
            REGEXP_REPLACE(r.budget, r'[^\d.]', '')
            AS NUMERIC
        ) AS parsed_budget,

        LOWER(TRIM(r.funding_type)) AS funding_type,

        SAFE_CAST(
            TRIM(r.max_redemptions_per_customer)
            AS INT64
        ) AS parsed_max_redemptions,

        UPPER(TRIM(r.status)) AS status,

        m.merchant_id AS fk_merchant_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.campaign_id)
            ORDER BY r.campaign_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.campaigns_raw` r

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.merchants` m
        ON TRIM(r.merchant_id) = m.merchant_id
)

SELECT

    *,

    ARRAY_CONCAT(

        IF(
            campaign_id IS NULL
            OR campaign_id = '',
            ['MISSING_PK: campaign_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: campaign_id occurs multiple times'],
            []
        ),

        IF(
            fk_merchant_id IS NULL,
            [
              CONCAT(
                'FK_NOT_FOUND: merchant_id ',
                COALESCE(merchant_id,'NULL'),
                ' does not exist in silver.merchants'
              )
            ],
            []
        ),

        IF(
            parsed_start_date IS NULL,
            ['INVALID_DATE: start_date is invalid'],
            []
        ),

        IF(
            parsed_end_date IS NULL,
            ['INVALID_DATE: end_date is invalid'],
            []
        ),

        IF(
            parsed_start_date IS NOT NULL
            AND parsed_end_date IS NOT NULL
            AND parsed_start_date > parsed_end_date,
            ['LOGIC_ERROR: start_date is after end_date'],
            []
        ),

        IF(
            parsed_min_spend IS NULL
            OR parsed_min_spend < 0,
            ['INVALID_AMOUNT: min_spend is negative or unparseable'],
            []
        ),

        IF(
            parsed_cashback_pct IS NULL
            OR parsed_cashback_pct <= 0
            OR parsed_cashback_pct > 100,
            ['INVALID_PERCENT: cashback_pct must be between 0 and 100'],
            []
        ),

        IF(
            parsed_cashback_cap IS NULL
            OR parsed_cashback_cap <= 0,
            ['INVALID_AMOUNT: cashback_cap must be > 0'],
            []
        ),

        IF(
            parsed_budget IS NULL
            OR parsed_budget <= 0,
            ['INVALID_AMOUNT: budget must be > 0'],
            []
        ),

        IF(
            parsed_max_redemptions IS NULL
            OR parsed_max_redemptions < 1,
            ['INVALID_NUMBER: max_redemptions_per_customer must be >= 1'],
            []
        )

    ) AS errors

FROM raw_data;


/* ==========================================================
   3. INVALID RECORDS
========================================================== */

INSERT INTO
`prj-imp-act-campaign.offers_silver.invalid_records`
(
    table_name,
    record_id,
    reason,
    raw_record,
    batch_id,
    rejected_at
)

SELECT

    'campaigns_raw',

    COALESCE(campaign_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_campaigns

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.campaigns` T

USING (

    SELECT

        campaign_id,
        merchant_id,
        objective,

        parsed_start_date AS start_date,
        parsed_end_date AS end_date,

        parsed_min_spend AS min_spend,
        parsed_cashback_pct AS cashback_pct,
        parsed_cashback_cap AS cashback_cap,
        parsed_budget AS budget,

        funding_type,

        parsed_max_redemptions
            AS max_redemptions_per_customer,

        status,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_campaigns

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.campaign_id = S.campaign_id

WHEN MATCHED THEN
UPDATE SET

    merchant_id = S.merchant_id,
    objective = S.objective,
    start_date = S.start_date,
    end_date = S.end_date,
    min_spend = S.min_spend,
    cashback_pct = S.cashback_pct,
    cashback_cap = S.cashback_cap,
    budget = S.budget,
    funding_type = S.funding_type,
    max_redemptions_per_customer = S.max_redemptions_per_customer,
    status = S.status,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    campaign_id,
    merchant_id,
    objective,
    start_date,
    end_date,
    min_spend,
    cashback_pct,
    cashback_cap,
    budget,
    funding_type,
    max_redemptions_per_customer,
    status,
    batch_id,
    ingested_at
)
VALUES
(
    S.campaign_id,
    S.merchant_id,
    S.objective,
    S.start_date,
    S.end_date,
    S.min_spend,
    S.cashback_pct,
    S.cashback_cap,
    S.budget,
    S.funding_type,
    S.max_redemptions_per_customer,
    S.status,
    S.batch_id,
    S.ingested_at
);