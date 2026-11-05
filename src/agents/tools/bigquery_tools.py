
import decimal
from typing import Any, Dict
import datetime
 
from google.cloud import bigquery
from agents.tools.policy_tools import validate_proposal
 
PROJECT_ID = "prj-imp-act-campaign"
BQ_CLIENT = bigquery.Client(project=PROJECT_ID)
 
 

def make_serializable(obj):
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [make_serializable(item) for item in obj]
    return obj
 
 
def get_campaign_terms(campaign_id: str) -> Dict[str, Any]:
    """Retrieve a campaign's configured terms from BigQuery.

    Returns the merchant, objective, spend and cashback terms, redemption
    constraints, budget, and current status.
    
    Args:
        campaign_id: The campaign ID to retrieve terms for.
        
    Returns:
        A dictionary containing campaign_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_campaign_terms with campaign_id={campaign_id}")
        
        sql = """
            SELECT
                campaign_id,
                merchant_id,
                objective,
                min_spend,
                cashback_pct,
                cashback_cap,
                budget,
                max_redemptions_per_customer,
                status
            FROM `prj-imp-act-campaign.offers_silver.campaigns`
            WHERE campaign_id = @campaign_id
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"campaign_id": campaign_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_campaign_terms('{campaign_id}'): {e}")
        return {
            "error": f"Failed retrieving campaign terms for '{campaign_id}': {str(e)}",
            "retryable": True,
            "campaign_id": campaign_id,
            "rows": []
        }

 
 
def get_campaign_performance(campaign_id: str) -> Dict[str, Any]:
    """Retrieve aggregate delivery and redemption metrics for a campaign.

    Returns targeting, delivery, redemption-rate, and cashback-spend measures
    from the gold campaign results table.
    
    Args:
        campaign_id: The campaign ID to retrieve performance metrics for.
        
    Returns:
        A dictionary containing campaign_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_campaign_performance with campaign_id={campaign_id}")

        sql = """
            SELECT
                campaign_id,
                merchant_id,
                targeted_customer_count,
                delivered_customer_count,
                redeeming_customer_count,
                redemption_rate_pct AS redemption_rate,
                cashback_amt_awarded AS cashback_spend
            FROM `prj-imp-act-campaign.offers_gold.gold_campaign_results`
            WHERE campaign_id = @campaign_id
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"campaign_id": campaign_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_campaign_performance('{campaign_id}'): {e}")
        return {
            "error": f"Failed retrieving campaign performance for '{campaign_id}': {str(e)}",
            "retryable": True,
            "campaign_id": campaign_id,
            "rows": []
        }
 
def get_spend_distribution(merchant_id: str) -> Dict[str, Any]:
    """Retrieve a merchant's historical spend profile from BigQuery.

    Returns posted transaction totals, average and median transaction amounts,
    and the distinct customer count.
    
    Args:
        merchant_id: The merchant ID to retrieve spend distribution for.
        
    Returns:
        A dictionary containing merchant_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_spend_distribution with merchant_id={merchant_id}")

        sql = """
            SELECT
                merchant_id,
                posted_txn_count,
                posted_amount_total,
                avg_txn_amount,
                median_txn_amount,
                distinct_customer_count
            FROM `prj-imp-act-campaign.offers_gold.gold_merchant_spend_profile`
            WHERE merchant_id = @merchant_id
            ORDER BY merchant_id
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id)
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"merchant_id": merchant_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_spend_distribution('{merchant_id}'): {e}")
        return {
            "error": f"Failed retrieving spend distribution for '{merchant_id}': {str(e)}",
            "retryable": True,
            "merchant_id": merchant_id,
            "rows": []
        }
 
def get_customer_reviews(merchant_id: str, limit: int = 20) -> Dict[str, Any]:
    """Retrieve a merchant's most recent customer reviews from BigQuery.

    Results are ordered newest first and limited by ``limit``.
    
    Args:
        merchant_id: The merchant ID to retrieve reviews for.
        limit: Maximum number of reviews to retrieve (default: 20).
        
    Returns:
        A dictionary containing merchant_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_customer_reviews with merchant_id={merchant_id}, limit={limit}")

        sql = """
            SELECT
                review_id,
                merchant_id,
                review_date,
                rating,
                review_text,
                source_ref
            FROM `prj-imp-act-campaign.offers_bronze.customer_reviews_raw`
            WHERE merchant_id = @merchant_id
            ORDER BY review_date DESC
            LIMIT @limit
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id),
                    bigquery.ScalarQueryParameter("limit", "INT64", limit),
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"merchant_id": merchant_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_customer_reviews('{merchant_id}', limit={limit}): {e}")
        return {
            "error": f"Failed retrieving customer reviews for '{merchant_id}': {str(e)}",
            "retryable": True,
            "merchant_id": merchant_id,
            "rows": []
        }

 
def get_merchant_feedback(merchant_id: str, limit: int = 20) -> Dict[str, Any]:
    """Retrieve a merchant's most recent feedback records from BigQuery.

    Results are ordered newest first and limited by ``limit``.
    
    Args:
        merchant_id: The merchant ID to retrieve feedback for.
        limit: Maximum number of feedback records to retrieve (default: 20).
        
    Returns:
        A dictionary containing merchant_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_merchant_feedback with merchant_id={merchant_id}, limit={limit}")

        sql = """
            SELECT
                feedback_id,
                merchant_id,
                event_date,
                feedback_text,
                source_ref,
                verification_status
            FROM `prj-imp-act-campaign.offers_bronze.merchant_feedback_raw`
            WHERE merchant_id = @merchant_id
            ORDER BY event_date DESC
            LIMIT @limit
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id),
                    bigquery.ScalarQueryParameter("limit", "INT64", limit),
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"merchant_id": merchant_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_merchant_feedback('{merchant_id}', limit={limit}): {e}")
        return {
            "error": f"Failed retrieving merchant feedback for '{merchant_id}': {str(e)}",
            "retryable": True,
            "merchant_id": merchant_id,
            "rows": []
        }
   
def get_delivery_metrics(campaign_id: str) -> Dict[str, Any]:
    """Retrieve a campaign's profile, terms, and quality fields from BigQuery.

    Returns merchant details, campaign dates and parameters, and the profile
    quality flag.
    
    Args:
        campaign_id: The campaign ID to retrieve delivery metrics for.
        
    Returns:
        A dictionary containing campaign_id and rows, or error details.
    """
    try:
        print(f"TOOL CALLED: get_delivery_metrics with campaign_id={campaign_id}")

        sql = """
            SELECT
                campaign_id,
                merchant_id,
                merchant_name,
                merchant_category,
                merchant_city,
                objective,
                cmp_start_date AS start_date,
                cmp_end_date AS end_date,
                min_spend,
                cashback_pct,
                cashback_cap,
                budget,
                funding_type,
                max_redemptions_per_customer,
                campaign_status,
                quality_flag
            FROM `prj-imp-act-campaign.offers_gold.gold_campaign_profile`
            WHERE campaign_id = @campaign_id
        """
        
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)
                ]
            ),
        )
        
        rows = [make_serializable(dict(r)) for r in job.result()]
        return {"campaign_id": campaign_id, "rows": rows}
        
    except Exception as e:
        print(f"Error in get_delivery_metrics('{campaign_id}'): {e}")
        return {
            "error": f"Failed retrieving delivery metrics for '{campaign_id}': {str(e)}",
            "retryable": True,
            "campaign_id": campaign_id,
            "rows": []
        }

 

def simulate_campaign_change(campaign_id: str, min_spend: float) -> Dict[str, Any]:
    """Replay proposed min_spend against historical transactions (retrospective only)."""
    try:
        min_spend = float(min_spend)
        if min_spend < 0:
            return {"error": "min_spend cannot be negative"}
    except (TypeError, ValueError):
        return {"error": "Invalid min_spend number"}

    sql = """
        WITH campaign AS (
            SELECT campaign_id, merchant_id, start_date, end_date, budget,
                   cashback_pct, cashback_cap, max_redemptions_per_customer,
                   min_spend AS current_min_spend
            FROM `prj-imp-act-campaign.offers_silver.campaigns`
            WHERE campaign_id = @campaign_id
        ),
        scenarios AS (
            SELECT 'current' AS scenario, current_min_spend AS min_spend FROM campaign
            UNION ALL
            SELECT 'proposed' AS scenario, @min_spend AS min_spend FROM campaign
        ),
        ranked_txns AS (
            SELECT s.scenario, t.customer_id, t.amount, c.cashback_pct, c.cashback_cap,
                   ROW_NUMBER() OVER (PARTITION BY s.scenario, t.customer_id ORDER BY t.txn_ts) as rn,
                   COALESCE(c.max_redemptions_per_customer, 1) as max_red
            FROM campaign c
            CROSS JOIN scenarios s
            JOIN `prj-imp-act-campaign.offers_silver.transactions` t ON t.merchant_id = c.merchant_id
            WHERE t.txn_status = 'POSTED' 
              AND DATE(t.txn_ts) BETWEEN c.start_date AND c.end_date
              AND t.amount >= s.min_spend
        )
        SELECT 
            s.scenario,
            s.min_spend,
            c.budget,
            COUNT(1) AS total_qualifying_txns,
            COUNTIF(r.rn <= r.max_red) AS eligible_txns,
            COUNT(DISTINCT IF(r.rn <= r.max_red, r.customer_id, NULL)) AS unique_customers,
            ROUND(SUM(IF(r.rn <= r.max_red, LEAST(r.amount * r.cashback_pct / 100, r.cashback_cap), 0)), 2) AS simulated_cashback
        FROM campaign c
        CROSS JOIN scenarios s
        LEFT JOIN ranked_txns r ON r.scenario = s.scenario
        GROUP BY s.scenario, s.min_spend, c.budget
    """
    
    try:
        job = BQ_CLIENT.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id),
                    bigquery.ScalarQueryParameter("min_spend", "NUMERIC", min_spend),
                ]
            ),
        )
        rows = {r["scenario"]: dict(r) for r in job.result()}
        if not rows or "current" not in rows or "proposed" not in rows:
            return {"error": f"Campaign {campaign_id} not found or incomplete data"}

        curr, prop = rows["current"], rows["proposed"]
        
        # Calculate delta safely converting Decimal values
        curr_sim = float(curr.get("simulated_cashback") or 0)
        prop_sim = float(prop.get("simulated_cashback") or 0)
        curr_cust = int(curr.get("unique_customers") or 0)
        prop_cust = int(prop.get("unique_customers") or 0)
        curr_txns = int(curr.get("eligible_txns") or 0)
        prop_txns = int(prop.get("eligible_txns") or 0)

        result = {
            "campaign_id": campaign_id,
            "current_scenario": curr,
            "proposed_scenario": prop,
            "delta": {
                "additional_customers": prop_cust - curr_cust,
                "additional_txns": prop_txns - curr_txns,
                "additional_cashback": round(prop_sim - curr_sim, 2),
            },
            "budget": prop.get("budget"),
            "budget_safe": prop_sim <= float(prop["budget"]) if prop.get("budget") is not None else True,
            "status": "APPROVED_REPLAY"
        }
        
        # Recursively sanitize all Decimal, date, and datetime types
        return make_serializable(result)

    except Exception as e:
        print(f"Error in simulate_campaign_change('{campaign_id}', min_spend={min_spend}): {e}")
        return {
            "error": f"Failed simulating campaign change: {str(e)}",
            "campaign_id": campaign_id,
            "status": "FAILED"
        }