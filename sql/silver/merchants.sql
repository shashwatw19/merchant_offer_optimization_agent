/* ==========================================================
   PROJECT: prj-imp-act-campaign
   SOURCE : offers_bronze.merchants_raw
   TARGET : offers_silver.merchants

   AUDIT COLUMNS
   -------------
   batch_id    -> inherited from Bronze
   ingested_at -> generated in Silver (IST)
========================================================== */


/* ==========================================================
   1. REFERENCE DATASET
========================================================== */

CREATE SCHEMA IF NOT EXISTS
`prj-imp-act-campaign.offers_reference`;


/* ==========================================================
   2. CITY MASTER
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_reference.city_master`
(
  city_id STRING NOT NULL,
  city_standard_name STRING NOT NULL
);


/* ==========================================================
   3. CITY MAPPING
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_reference.city_mapping`
(
  city_id STRING NOT NULL,
  city_name STRING NOT NULL
);


/* ==========================================================
   4. LOAD MASTER DATA (RUN ONCE)
========================================================== */

MERGE
`prj-imp-act-campaign.offers_reference.city_master` T
USING (
  SELECT * FROM UNNEST([
    STRUCT('100' AS city_id,'Mumbai' AS city_standard_name),
    STRUCT('101' AS city_id,'Pune' AS city_standard_name),
    STRUCT('102' AS city_id,'Delhi' AS city_standard_name),
    STRUCT('103' AS city_id,'Bengaluru' AS city_standard_name)
  ])
) S
ON T.city_id = S.city_id
WHEN NOT MATCHED THEN
INSERT(city_id,city_standard_name)
VALUES(S.city_id,S.city_standard_name);


MERGE
`prj-imp-act-campaign.offers_reference.city_mapping` T
USING (
  SELECT * FROM UNNEST([

    STRUCT('100' AS city_id,'Mumbai' AS city_name),
    STRUCT('100','Bombay'),
    STRUCT('100','Bambai'),
    STRUCT('100','Bombai'),
    STRUCT('100','Mum Bai'),

    STRUCT('101','Pune'),
    STRUCT('101','Poona'),

    STRUCT('102','Delhi'),
    STRUCT('102','New Delhi'),

    STRUCT('103','Bangalore'),
    STRUCT('103','Bengaluru')

  ])
) S
ON T.city_id = S.city_id
AND T.city_name = S.city_name

WHEN NOT MATCHED THEN
INSERT(city_id,city_name)
VALUES(S.city_id,S.city_name);


/* ==========================================================
   5. MERCHANT SILVER TABLE
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_silver.merchants`
(
    merchant_id STRING NOT NULL,
    name STRING NOT NULL,
    category STRING,
    city STRING,
    status STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = 'Silver merchant master table with standardized city mappings and audit columns'
);


/* ==========================================================
   6. STAGING + CLEANING + CITY STANDARDIZATION
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_merchants AS

WITH raw_data AS (

    SELECT
        TRIM(merchant_id) AS merchant_id,
        TRIM(name) AS name,
        TRIM(category) AS category,
        TRIM(city) AS city_raw,
        UPPER(TRIM(status)) AS status,

        r.batch_id AS batch_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(merchant_id)
            ORDER BY merchant_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.merchants_raw` r
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

        merchant_id,
        name,
        category,

        city_standard_name AS city,

        batch_id,

        city_raw,
        city_id,
        status,
        rn,
        raw_record,

        ARRAY_CONCAT(

            IF(
                merchant_id IS NULL
                OR merchant_id = '',
                ['MISSING_PK: merchant_id is null or blank'],
                []
            ),

            IF(
                rn > 1,
                ['DUPLICATE_PK: merchant_id occurs multiple times'],
                []
            ),

            IF(
                name IS NULL
                OR name = '',
                ['MISSING_REQUIRED_FIELD: merchant name is blank'],
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
   7. INVALID RECORDS
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

    'merchants_raw',

    COALESCE(merchant_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_merchants

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   8. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.merchants` T

USING (

    SELECT
        merchant_id,
        name,
        category,
        city,
        status,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_merchants

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.merchant_id = S.merchant_id

WHEN MATCHED THEN
UPDATE SET
    name = S.name,
    category = S.category,
    city = S.city,
    status = S.status,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    merchant_id,
    name,
    category,
    city,
    status,
    batch_id,
    ingested_at
)
VALUES
(
    S.merchant_id,
    S.name,
    S.category,
    S.city,
    S.status,
    S.batch_id,
    S.ingested_at
);