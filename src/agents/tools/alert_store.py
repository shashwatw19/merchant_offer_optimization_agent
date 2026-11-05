from google.cloud import bigquery

PROJECT_ID = "prj-imp-act-campaign"
ALERT_TABLE = f"{PROJECT_ID}.offers_gold.alerts"

client = bigquery.Client(project=PROJECT_ID)


def ensure_alert_table():
    """
    Table already exists in BigQuery.
    Keeping function so existing code doesn't break.
    """
    pass


def fetch_pending_alerts(limit=20):
    """
    Fetch alerts with status = OPEN
    """

    query = f"""
    SELECT
        alert_id,
        campaign_id,
        merchant_id,
        rule_id,
        metric_name,
        metric_value,
        threshold_value,
        status,
        created_at
    FROM `{ALERT_TABLE}`
    WHERE status = 'OPEN'
    ORDER BY created_at ASC
    LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "limit",
                "INT64",
                limit
            )
        ]
    )

    query_job = client.query(
        query,
        job_config=job_config
    )

    results = query_job.result()

    alerts = []

    for row in results:
        alerts.append(dict(row.items()))

    return alerts


def update_alert_status(alert_id, status):
    """
    Update alert status to PROCESSED / ERROR
    """

    query = f"""
    UPDATE `{ALERT_TABLE}`
    SET status = @status
    WHERE alert_id = @alert_id
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter(
                "status",
                "STRING",
                status
            ),
            bigquery.ScalarQueryParameter(
                "alert_id",
                "STRING",
                alert_id
            ),
        ]
    )

    client.query(
        query,
        job_config=job_config
    ).result()

    print(
        f"Updated alert {alert_id} -> {status}"
    )