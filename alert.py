import argparse
import hashlib
from datetime import datetime

from google.cloud import bigquery

PROJECT_ID = "prj-imp-act-campaign"
ALERT_TABLE = "prj-imp-act-campaign.offers_gold.alerts"

QUERY_BY_RULE = {

    # R1: Low Redemption Rate
    "R1": """
        WITH campaign_fact AS (
            SELECT
                campaign_id,
                merchant_id,
                ROUND(
                    SAFE_DIVIDE(
                        redeeming_customer_count,
                        NULLIF(targeted_customer_count, 0)
                    ) * 100,
                    2
                ) AS redemption_rate
            FROM `prj-imp-act-campaign.offers_gold.gold_campaign_results`
            WHERE targeted_customer_count > 0
        )
        SELECT
            campaign_id,
            merchant_id,
            'R1' AS rule_id,
            redemption_rate AS metric_value,
            5.00 AS threshold,
            'OPEN' AS status
        FROM campaign_fact
        WHERE redemption_rate < 5
        ORDER BY campaign_id
    """,

    # R2: Campaign Avg Transaction Amount < 85% Merchant Average
    "R2": """
        WITH campaign_fact AS (
            SELECT
                cr.campaign_id,
                cr.merchant_id,

                ROUND(
                    SAFE_DIVIDE(
                        cr.posted_txn_amount,
                        NULLIF(cr.posted_txn_count, 0)
                    ),
                    2
                ) AS avg_txn_amount,

                msp.avg_txn_amount AS avg_merchant_txn_amount

            FROM `prj-imp-act-campaign.offers_gold.gold_campaign_results` cr

            INNER JOIN
            `prj-imp-act-campaign.offers_gold.gold_merchant_spend_profile` msp
                ON cr.merchant_id = msp.merchant_id

            WHERE cr.posted_txn_count > 0
              AND msp.avg_txn_amount IS NOT NULL
        )

        SELECT
            campaign_id,
            merchant_id,
            'R2' AS rule_id,
            avg_txn_amount AS metric_value,
            ROUND(avg_merchant_txn_amount * 0.85, 2) AS threshold,
            'OPEN' AS status
        FROM campaign_fact
        WHERE avg_txn_amount < (avg_merchant_txn_amount * 0.85)
        ORDER BY campaign_id
    """,

    # R3: Existing Customer Share >= 75%
    "R3": """
        WITH redeeming_customers AS (

            SELECT
                c.campaign_id,
                c.merchant_id,
                rr.customer_id,

                MAX(
                    CASE
                        WHEN CAST(tx.txn_ts AS DATETIME)
                             < DATETIME(c.start_date)
                         AND tx.merchant_id = c.merchant_id
                         AND UPPER(tx.txn_status) = 'POSTED'
                        THEN 1
                        ELSE 0
                    END
                ) AS is_existing_customer

            FROM `prj-imp-act-campaign.offers_silver.offer_redemptions` rr

            INNER JOIN
            `prj-imp-act-campaign.offers_silver.campaigns` c
                ON c.campaign_id = rr.campaign_id

            LEFT JOIN
            `prj-imp-act-campaign.offers_silver.transactions` tx
                ON tx.customer_id = rr.customer_id
               AND tx.merchant_id = c.merchant_id
               AND UPPER(tx.txn_status) = 'POSTED'
               AND CAST(tx.txn_ts AS DATETIME)
                   < DATETIME(c.start_date)

            WHERE UPPER(c.objective) = 'ACQUIRE_NEW'

            GROUP BY
                c.campaign_id,
                c.merchant_id,
                rr.customer_id
        ),

        campaign_fact AS (

            SELECT
                campaign_id,
                merchant_id,

                COUNT(DISTINCT customer_id)
                    AS redeeming_customers,

                COUNT(
                    DISTINCT CASE
                        WHEN is_existing_customer = 1
                        THEN customer_id
                    END
                ) AS existing_customer_redeemers,

                ROUND(
                    SAFE_DIVIDE(
                        COUNT(
                            DISTINCT CASE
                                WHEN is_existing_customer = 1
                                THEN customer_id
                            END
                        ),
                        COUNT(DISTINCT customer_id)
                    ),
                    2
                ) AS existing_customer_share

            FROM redeeming_customers

            GROUP BY
                campaign_id,
                merchant_id
        )

        SELECT
            campaign_id,
            merchant_id,
            'R3' AS rule_id,
            existing_customer_share * 100 AS metric_value,
            75.00 AS threshold,
            'OPEN' AS status
        FROM campaign_fact
        WHERE existing_customer_share >= 0.75
        ORDER BY campaign_id
    """
}

METRIC_NAME_MAP = {
    "R1": "redemption_rate",
    "R2": "avg_campaign_txn_amount",
    "R3": "existing_customer_share_pct"
}


def generate_alert_id(rule_id, campaign_id):
    raw = f"{rule_id}:{campaign_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    numeric = int(digest[:8], 16)
    return f"A{numeric % 9000 + 1000}"


def build_alert_payload(row):

    rule_id = row["rule_id"]

    return {
        "alert_id": generate_alert_id(
            rule_id,
            row["campaign_id"]
        ),
        "campaign_id": row["campaign_id"],
        "merchant_id": row.get("merchant_id"),
        "rule_id": rule_id,
        "metric_name": METRIC_NAME_MAP[rule_id],
        "metric_value": float(row["metric_value"]),
        "threshold_value": float(row["threshold"]),
        "status": row["status"],
        "created_at": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    }


def fetch_rule_rows(client, rule_id):

    query = QUERY_BY_RULE[rule_id]

    rows = client.query(query).result()

    return [dict(row) for row in rows]


def run_all_alerts(project_id=PROJECT_ID):

    client = bigquery.Client(project=project_id)

    alerts = []

    for rule_id in ["R1", "R2", "R3"]:

        rows = fetch_rule_rows(
            client,
            rule_id
        )

        for row in rows:
            alerts.append(
                build_alert_payload(row)
            )

    return alerts


def save_alerts_to_bigquery(client, alerts):

    if not alerts:
        return

    errors = client.insert_rows_json(
        ALERT_TABLE,
        alerts
    )

    if errors:
        raise RuntimeError(
            f"BigQuery insert failed: {errors}"
        )

    print(
        f"Inserted {len(alerts)} alerts into {ALERT_TABLE}"
    )


def main():

    parser = argparse.ArgumentParser(
        description="Generate merchant offer alerts"
    )

    parser.add_argument(
        "--project",
        default=PROJECT_ID,
        help="Google Cloud project id"
    )

    args = parser.parse_args()

    alerts = run_all_alerts(
        args.project
    )

    if not alerts:
        print("No alerts triggered.")
        return

    client = bigquery.Client(
        project=args.project
    )

    save_alerts_to_bigquery(
        client,
        alerts
    )

    print(
        f"Successfully processed {len(alerts)} alerts."
    )


if __name__ == "__main__":
    main()