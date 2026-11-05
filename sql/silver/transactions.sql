/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.transactions_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.transactions

   FK LOOKUP TABLES
   ----------------
   prj-imp-act-campaign.offers_silver.customers
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
`prj-imp-act-campaign.offers_silver.transactions`
(
    txn_id STRING NOT NULL,
    customer_id STRING NOT NULL,
    merchant_id STRING NOT NULL,

    txn_ts DATETIME NOT NULL,

    amount NUMERIC NOT NULL,
    txn_status STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = 'Silver transactions table with FK validations and audit tracking'
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_transactions AS

WITH raw_data AS (

    SELECT

        TRIM(r.txn_id) AS txn_id,

        TRIM(r.customer_id) AS customer_id,

        TRIM(r.merchant_id) AS merchant_id,

        r.batch_id AS batch_id,

        DATETIME(
            COALESCE(
                SAFE_CAST(TRIM(r.txn_ts) AS TIMESTAMP),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%d %H:%M:%S',
                    TRIM(r.txn_ts)
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%dT%H:%M:%E*SZ',
                    TRIM(r.txn_ts)
                )
            ),
            'Asia/Kolkata'
        ) AS parsed_txn_ts,

        SAFE_CAST(
            REGEXP_REPLACE(
                r.amount,
                r'[^\d.]',
                ''
            )
            AS NUMERIC
        ) AS parsed_amount,

        UPPER(TRIM(r.txn_status)) AS txn_status,

        c.customer_id AS fk_customer_id,

        m.merchant_id AS fk_merchant_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.txn_id)
            ORDER BY r.txn_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.transactions_raw` r

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.customers` c
        ON TRIM(r.customer_id) = c.customer_id

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.merchants` m
        ON TRIM(r.merchant_id) = m.merchant_id

)

SELECT

    *,

    ARRAY_CONCAT(

        IF(
            txn_id IS NULL
            OR txn_id = '',
            ['MISSING_PK: txn_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: txn_id occurs multiple times'],
            []
        ),

        IF(
            fk_customer_id IS NULL,
            [
                CONCAT(
                    'FK_NOT_FOUND: customer_id ',
                    COALESCE(customer_id,'NULL'),
                    ' does not exist in silver.customers'
                )
            ],
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
            parsed_txn_ts IS NULL,
            ['INVALID_TIMESTAMP: txn_ts cannot be parsed'],
            []
        ),

        IF(
            parsed_amount IS NULL
            OR parsed_amount <= 0,
            ['INVALID_AMOUNT: amount must be > 0'],
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

    'transactions_raw',

    COALESCE(txn_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_transactions

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.transactions` T

USING (

    SELECT

        txn_id,
        customer_id,
        merchant_id,

        parsed_txn_ts AS txn_ts,

        parsed_amount AS amount,

        txn_status,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_transactions

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.txn_id = S.txn_id

WHEN MATCHED THEN
UPDATE SET

    customer_id = S.customer_id,
    merchant_id = S.merchant_id,
    txn_ts = S.txn_ts,
    amount = S.amount,
    txn_status = S.txn_status,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    txn_id,
    customer_id,
    merchant_id,
    txn_ts,
    amount,
    txn_status,
    batch_id,
    ingested_at
)
VALUES
(
    S.txn_id,
    S.customer_id,
    S.merchant_id,
    S.txn_ts,
    S.amount,
    S.txn_status,
    S.batch_id,
    S.ingested_at
);