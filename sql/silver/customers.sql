/* ==========================================================
   PROJECT : prj-imp-act-campaign
   SOURCE  : offers_bronze.customers_raw
   TARGET  : offers_silver.customers

   AUDIT COLUMNS
   -------------
   batch_id   -> inherited from Bronze
   ingested_at -> generated in Silver (IST)
========================================================== */


/* ==========================================================
   1. SILVER TABLE
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_silver.customers`
(
    customer_id STRING NOT NULL,
    city STRING,
    segment STRING,
    marketing_eligible BOOL,
    card_status STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = "Silver customer master table with standardized city and audit fields"
);


/* ==========================================================
   2. STAGE + CLEAN + CITY STANDARDIZATION
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_customers AS

WITH raw_data AS (

    SELECT

        TRIM(customer_id) AS customer_id,

        TRIM(city) AS city_raw,

        TRIM(segment) AS segment,

        r.batch_id AS batch_id,

        CASE
            WHEN LOWER(TRIM(marketing_eligible))
                IN ('true','1','yes','t')
                THEN TRUE

            WHEN LOWER(TRIM(marketing_eligible))
                IN ('false','0','no','f')
                THEN FALSE

            ELSE NULL
        END AS marketing_eligible_bool,

        marketing_eligible AS raw_marketing_eligible,

        UPPER(TRIM(card_status)) AS card_status,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(customer_id)
            ORDER BY customer_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.customers_raw` r
),

city_standardized AS (

    SELECT

        r.*,
        cm.city_id,
        mst.city_standard_name

    FROM raw_data r

    LEFT JOIN
    `prj-imp-act-campaign.offers_reference.city_mapping` cm
       ON UPPER(TRIM(r.city_raw))
       = UPPER(TRIM(cm.city_name))

    LEFT JOIN
    `prj-imp-act-campaign.offers_reference.city_master` mst
       ON cm.city_id = mst.city_id

),

validated AS (

    SELECT

        customer_id,

        city_standard_name AS city,

        segment,

        marketing_eligible_bool AS marketing_eligible,

        raw_marketing_eligible,

        card_status,

        batch_id,

        city_raw,
        city_id,

        rn,

        raw_record,

        ARRAY_CONCAT(

            IF(
                customer_id IS NULL
                OR customer_id = '',
                ['MISSING_PK: customer_id is null or blank'],
                []
            ),

            IF(
                rn > 1,
                ['DUPLICATE_PK: customer_id occurs multiple times'],
                []
            ),

            IF(
                raw_marketing_eligible IS NOT NULL
                AND marketing_eligible_bool IS NULL,
                ['INVALID_BOOLEAN: marketing_eligible cannot be cast'],
                []
            ),

            IF(
                city_raw IS NULL
                OR city_raw = '',
                ['MISSING_REQUIRED_FIELD: city is blank'],
                []
            ),

            IF(
                city_raw IS NOT NULL
                AND city_raw <> ''
                AND city_id IS NULL,
                ['CITY_NOT_FOUND_IN_MAPPING_TABLE'],
                []
            )

        ) AS errors

    FROM city_standardized

)

SELECT *
FROM validated;


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

    'customers_raw',

    COALESCE(customer_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_customers

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS INTO SILVER
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.customers` T

USING (

    SELECT

        customer_id,
        city,
        segment,
        marketing_eligible,
        card_status,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_customers

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.customer_id = S.customer_id

WHEN MATCHED THEN
UPDATE SET

    city = S.city,
    segment = S.segment,
    marketing_eligible = S.marketing_eligible,
    card_status = S.card_status,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    customer_id,
    city,
    segment,
    marketing_eligible,
    card_status,
    batch_id,
    ingested_at
)
VALUES
(
    S.customer_id,
    S.city,
    S.segment,
    S.marketing_eligible,
    S.card_status,
    S.batch_id,
    S.ingested_at
);
