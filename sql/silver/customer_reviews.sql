/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.customer_reviews_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.customer_reviews

   FK LOOKUP TABLE
   ---------------
   prj-imp-act-campaign.offers_silver.merchants

   ERROR TABLE
   -----------
   prj-imp-act-campaign.offers_silver.invalid_records

   AUDIT COLUMNS
   -------------
   batch_id   -> inherited from Bronze
   ingested_at -> generated in Silver (IST)
========================================================== */


/* ==========================================================
   1. SILVER TABLE
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_silver.customer_reviews`
(
    review_id STRING NOT NULL,
    merchant_id STRING NOT NULL,
    review_date DATE NOT NULL,

    collected_at DATETIME,

    rating NUMERIC,
    review_text STRING,
    source_ref STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = "Silver customer reviews table with merchant validation and standardized timestamps"
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_customer_reviews AS

WITH raw_data AS (

    SELECT

        TRIM(r.review_id) AS review_id,

        TRIM(r.merchant_id) AS merchant_id,

        r.batch_id AS batch_id,

        COALESCE(
            SAFE.PARSE_DATE(
                '%Y-%m-%d',
                TRIM(r.review_date)
            ),
            SAFE.PARSE_DATE(
                '%d-%m-%Y',
                TRIM(r.review_date)
            ),
            SAFE_CAST(
                TRIM(r.review_date)
                AS DATE
            )
        ) AS parsed_review_date,

        DATETIME(
            COALESCE(
                SAFE_CAST(
                    TRIM(r.collected_at)
                    AS TIMESTAMP
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%d %H:%M:%S',
                    TRIM(r.collected_at)
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%dT%H:%M:%E*SZ',
                    TRIM(r.collected_at)
                )
            ),
            'Asia/Kolkata'
        ) AS parsed_collected_at,

        SAFE_CAST(
            TRIM(r.rating)
            AS NUMERIC
        ) AS parsed_rating,

        TRIM(r.review_text) AS review_text,

        TRIM(r.source_ref) AS source_ref,

        m.merchant_id AS fk_merchant_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.review_id)
            ORDER BY r.review_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.customer_reviews_raw` r

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.merchants` m
        ON TRIM(r.merchant_id) = m.merchant_id

)

SELECT

    *,

    ARRAY_CONCAT(

        IF(
            review_id IS NULL
            OR review_id = '',
            ['MISSING_PK: review_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: review_id occurs multiple times'],
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
            parsed_review_date IS NULL,
            ['INVALID_DATE: review_date cannot be parsed'],
            []
        ),

        IF(
            parsed_rating IS NOT NULL
            AND (
                parsed_rating < 1.0
                OR parsed_rating > 5.0
            ),
            ['INVALID_RANGE: rating must be between 1.0 and 5.0'],
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

    'customer_reviews_raw',

    COALESCE(review_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_customer_reviews

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.customer_reviews` T

USING (

    SELECT

        review_id,

        merchant_id,

        parsed_review_date AS review_date,

        parsed_collected_at AS collected_at,

        parsed_rating AS rating,

        review_text,

        source_ref,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_customer_reviews

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.review_id = S.review_id

WHEN MATCHED THEN
UPDATE SET

    merchant_id = S.merchant_id,
    review_date = S.review_date,
    collected_at = S.collected_at,
    rating = S.rating,
    review_text = S.review_text,
    source_ref = S.source_ref,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    review_id,
    merchant_id,
    review_date,
    collected_at,
    rating,
    review_text,
    source_ref,
    batch_id,
    ingested_at
)
VALUES
(
    S.review_id,
    S.merchant_id,
    S.review_date,
    S.collected_at,
    S.rating,
    S.review_text,
    S.source_ref,
    S.batch_id,
    S.ingested_at
);