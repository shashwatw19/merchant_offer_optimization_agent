/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.merchant_feedback_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.merchant_feedback

   FK LOOKUP TABLE
   ---------------
   prj-imp-act-campaign.offers_silver.merchants

   ERROR TABLE
   -----------
   prj-imp-act-campaign.offers_silver.invalid_records

   AUDIT COLUMNS
   -------------
   batch_id    -> inherited from Bronze
   ingested_at -> generated in Silver (IST)
========================================================== */


/* ==========================================================
   1. SILVER TABLE
========================================================== */

CREATE TABLE IF NOT EXISTS
`prj-imp-act-campaign.offers_silver.merchant_feedback`
(
    feedback_id STRING NOT NULL,
    merchant_id STRING NOT NULL,
    event_date DATE NOT NULL,

    recorded_at DATETIME,

    feedback_text STRING,
    source_ref STRING,
    verification_status STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_merchant_feedback AS

WITH raw_data AS (

    SELECT

        TRIM(r.feedback_id) AS feedback_id,

        TRIM(r.merchant_id) AS merchant_id,

        r.batch_id AS batch_id,

        COALESCE(
            SAFE.PARSE_DATE('%Y-%m-%d', TRIM(r.event_date)),
            SAFE.PARSE_DATE('%d-%m-%Y', TRIM(r.event_date)),
            SAFE_CAST(TRIM(r.event_date) AS DATE)
        ) AS parsed_event_date,

        DATETIME(
            COALESCE(
                SAFE_CAST(TRIM(r.recorded_at) AS TIMESTAMP),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%d %H:%M:%S',
                    TRIM(r.recorded_at)
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%dT%H:%M:%E*SZ',
                    TRIM(r.recorded_at)
                )
            ),
            'Asia/Kolkata'
        ) AS parsed_recorded_at,

        TRIM(r.feedback_text) AS feedback_text,

        TRIM(r.source_ref) AS source_ref,

        UPPER(TRIM(r.verification_status))
            AS verification_status,

        m.merchant_id AS fk_merchant_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.feedback_id)
            ORDER BY r.feedback_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.merchant_feedback_raw` r

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.merchants` m
        ON TRIM(r.merchant_id) = m.merchant_id

)

SELECT

    *,

    ARRAY_CONCAT(

        IF(
            feedback_id IS NULL
            OR feedback_id = '',
            ['MISSING_PK: feedback_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: feedback_id occurs multiple times'],
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
            parsed_event_date IS NULL,
            ['INVALID_DATE: event_date cannot be parsed'],
            []
        ),

        IF(
            verification_status IS NOT NULL
            AND verification_status <> ''
            AND verification_status NOT IN
            (
                'UNVERIFIED',
                'MERCHANT_REPORTED'
            ),
            [
                'INVALID_VALUE: verification_status must be UNVERIFIED or MERCHANT_REPORTED'
            ],
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

    'merchant_feedback_raw',

    COALESCE(feedback_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_merchant_feedback

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.merchant_feedback` T

USING (

    SELECT

        feedback_id,

        merchant_id,

        parsed_event_date AS event_date,

        parsed_recorded_at AS recorded_at,

        feedback_text,

        source_ref,

        verification_status,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_merchant_feedback

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.feedback_id = S.feedback_id

WHEN MATCHED THEN
UPDATE SET

    merchant_id = S.merchant_id,
    event_date = S.event_date,
    recorded_at = S.recorded_at,
    feedback_text = S.feedback_text,
    source_ref = S.source_ref,
    verification_status = S.verification_status,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    feedback_id,
    merchant_id,
    event_date,
    recorded_at,
    feedback_text,
    source_ref,
    verification_status,
    batch_id,
    ingested_at
)
VALUES
(
    S.feedback_id,
    S.merchant_id,
    S.event_date,
    S.recorded_at,
    S.feedback_text,
    S.source_ref,
    S.verification_status,
    S.batch_id,
    S.ingested_at
);