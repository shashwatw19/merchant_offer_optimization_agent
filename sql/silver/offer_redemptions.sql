/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.offer_redemptions_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.offer_redemptions

   FK LOOKUP TABLES
   ----------------
   prj-imp-act-campaign.offers_silver.transactions
   prj-imp-act-campaign.offers_silver.campaigns
   prj-imp-act-campaign.offers_silver.customers

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
`prj-imp-act-campaign.offers_silver.offer_redemptions`
(
    redemption_id STRING NOT NULL,
    txn_id STRING NOT NULL,
    campaign_id STRING NOT NULL,
    customer_id STRING NOT NULL,
    awarded_cashback NUMERIC NOT NULL,
    status STRING,

    awarded_at DATETIME NOT NULL,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = 'Silver offer redemption table with FK validations and audit fields'
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_offer_redemptions AS

WITH raw_data AS (

    SELECT

        TRIM(r.redemption_id) AS redemption_id,

        TRIM(r.txn_id) AS txn_id,

        TRIM(r.campaign_id) AS campaign_id,

        TRIM(r.customer_id) AS customer_id,

        r.batch_id AS batch_id,

        SAFE_CAST(
            REGEXP_REPLACE(
                r.awarded_cashback,
                r'[^\d.]',
                ''
            ) AS NUMERIC
        ) AS parsed_cashback,

        UPPER(TRIM(r.status)) AS status,

        DATETIME(
            COALESCE(
                SAFE_CAST(TRIM(r.awarded_at) AS TIMESTAMP),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%d %H:%M:%S',
                    TRIM(r.awarded_at)
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%dT%H:%M:%E*SZ',
                    TRIM(r.awarded_at)
                )
            ),
            'Asia/Kolkata'
        ) AS parsed_awarded_at,

        txn.txn_id AS fk_txn_id,

        txn.customer_id AS txn_customer_id,

        txn.merchant_id AS txn_merchant_id,

        camp.campaign_id AS fk_campaign_id,

        camp.merchant_id AS camp_merchant_id,

        cust.customer_id AS fk_customer_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.redemption_id)
            ORDER BY r.redemption_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.offer_redemptions_raw` r

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.transactions` txn
        ON TRIM(r.txn_id) = txn.txn_id

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.campaigns` camp
        ON TRIM(r.campaign_id) = camp.campaign_id

    LEFT JOIN
    `prj-imp-act-campaign.offers_silver.customers` cust
        ON TRIM(r.customer_id) = cust.customer_id

)

SELECT

    *,

    ARRAY_CONCAT(

        IF(
            redemption_id IS NULL
            OR redemption_id = '',
            ['MISSING_PK: redemption_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: redemption_id occurs multiple times'],
            []
        ),

        IF(
            fk_txn_id IS NULL,
            [
                CONCAT(
                    'FK_NOT_FOUND: txn_id ',
                    COALESCE(txn_id,'NULL'),
                    ' does not exist in silver.transactions'
                )
            ],
            []
        ),

        IF(
            fk_campaign_id IS NULL,
            [
                CONCAT(
                    'FK_NOT_FOUND: campaign_id ',
                    COALESCE(campaign_id,'NULL'),
                    ' does not exist in silver.campaigns'
                )
            ],
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
            fk_txn_id IS NOT NULL
            AND txn_customer_id <> customer_id,
            [
                'INTEGRITY_MISMATCH: redemption customer_id does not match transaction customer_id'
            ],
            []
        ),

        IF(
            fk_txn_id IS NOT NULL
            AND fk_campaign_id IS NOT NULL
            AND txn_merchant_id <> camp_merchant_id,
            [
                'INTEGRITY_MISMATCH: transaction merchant does not match campaign merchant'
            ],
            []
        ),

        IF(
            parsed_cashback IS NULL
            OR parsed_cashback <= 0,
            ['INVALID_AMOUNT: awarded_cashback must be > 0'],
            []
        ),

        IF(
            parsed_awarded_at IS NULL,
            ['INVALID_TIMESTAMP: awarded_at cannot be parsed'],
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

    'offer_redemptions_raw',

    COALESCE(redemption_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_offer_redemptions

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.offer_redemptions` T

USING (

    SELECT

        redemption_id,

        txn_id,

        campaign_id,

        customer_id,

        parsed_cashback AS awarded_cashback,

        status,

        parsed_awarded_at AS awarded_at,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_offer_redemptions

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.redemption_id = S.redemption_id

WHEN MATCHED THEN
UPDATE SET

    txn_id = S.txn_id,
    campaign_id = S.campaign_id,
    customer_id = S.customer_id,
    awarded_cashback = S.awarded_cashback,
    status = S.status,
    awarded_at = S.awarded_at,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    redemption_id,
    txn_id,
    campaign_id,
    customer_id,
    awarded_cashback,
    status,
    awarded_at,
    batch_id,
    ingested_at
)
VALUES
(
    S.redemption_id,
    S.txn_id,
    S.campaign_id,
    S.customer_id,
    S.awarded_cashback,
    S.status,
    S.awarded_at,
    S.batch_id,
    S.ingested_at
);