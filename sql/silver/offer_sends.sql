/* ==========================================================
   PROJECT : prj-imp-act-campaign

   SOURCE
   -------
   prj-imp-act-campaign.offers_bronze.offer_sends_raw

   TARGET
   -------
   prj-imp-act-campaign.offers_silver.offer_sends

   FK LOOKUP TABLES
   ----------------
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
`prj-imp-act-campaign.offers_silver.offer_sends`
(
    send_id STRING NOT NULL,
    campaign_id STRING NOT NULL,
    customer_id STRING NOT NULL,

    sent_at DATETIME NOT NULL,

    delivery_status STRING,
    channel STRING,

    batch_id STRING,

    ingested_at DATETIME NOT NULL
)
OPTIONS (
    description = 'Silver offer sends table with campaign/customer FK validation and audit tracking'
);


/* ==========================================================
   2. STAGE + CLEAN + VALIDATE
========================================================== */

CREATE OR REPLACE TEMP TABLE _stg_offer_sends AS

WITH raw_data AS (

    SELECT

        TRIM(r.send_id) AS send_id,

        TRIM(r.campaign_id) AS campaign_id,

        TRIM(r.customer_id) AS customer_id,

        r.batch_id AS batch_id,

        DATETIME(
            COALESCE(
                SAFE_CAST(TRIM(r.sent_at) AS TIMESTAMP),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%d %H:%M:%S',
                    TRIM(r.sent_at)
                ),
                SAFE.PARSE_TIMESTAMP(
                    '%Y-%m-%dT%H:%M:%E*SZ',
                    TRIM(r.sent_at)
                )
            ),
            'Asia/Kolkata'
        ) AS parsed_sent_at,

        UPPER(TRIM(r.delivery_status)) AS delivery_status,

        LOWER(TRIM(r.channel)) AS channel,

        camp.campaign_id AS fk_campaign_id,

        cust.customer_id AS fk_customer_id,

        TO_JSON(r) AS raw_record,

        ROW_NUMBER() OVER (
            PARTITION BY TRIM(r.send_id)
            ORDER BY r.send_id
        ) AS rn

    FROM
    `prj-imp-act-campaign.offers_bronze.offer_sends_raw` r

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
            send_id IS NULL
            OR send_id = '',
            ['MISSING_PK: send_id is null or blank'],
            []
        ),

        IF(
            rn > 1,
            ['DUPLICATE_PK: send_id occurs multiple times'],
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
            parsed_sent_at IS NULL,
            ['INVALID_TIMESTAMP: sent_at cannot be parsed'],
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

    'offer_sends_raw',

    COALESCE(send_id,'UNKNOWN'),

    ARRAY_TO_STRING(errors,'; '),

    raw_record,

    batch_id,

    CURRENT_TIMESTAMP()

FROM _stg_offer_sends

WHERE ARRAY_LENGTH(errors) > 0;


/* ==========================================================
   4. UPSERT VALID RECORDS
========================================================== */

MERGE
`prj-imp-act-campaign.offers_silver.offer_sends` T

USING (

    SELECT

        send_id,
        campaign_id,
        customer_id,

        parsed_sent_at AS sent_at,

        delivery_status,

        channel,

        batch_id,

        CURRENT_DATETIME('Asia/Kolkata')
            AS ingested_at

    FROM _stg_offer_sends

    WHERE ARRAY_LENGTH(errors) = 0

) S

ON T.send_id = S.send_id

WHEN MATCHED THEN
UPDATE SET

    campaign_id = S.campaign_id,
    customer_id = S.customer_id,
    sent_at = S.sent_at,
    delivery_status = S.delivery_status,
    channel = S.channel,
    batch_id = S.batch_id,
    ingested_at = S.ingested_at

WHEN NOT MATCHED THEN
INSERT
(
    send_id,
    campaign_id,
    customer_id,
    sent_at,
    delivery_status,
    channel,
    batch_id,
    ingested_at
)
VALUES
(
    S.send_id,
    S.campaign_id,
    S.customer_id,
    S.sent_at,
    S.delivery_status,
    S.channel,
    S.batch_id,
    S.ingested_at
);