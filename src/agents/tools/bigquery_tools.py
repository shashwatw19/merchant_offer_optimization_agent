from typing import Any, Dict
from google.cloud import bigquery
import core.bigquery_client as bq_client
from core.config import get_config
from core.logging import logger
from domain.simulator import HistoricalReplaySimulator

_SIMULATOR = HistoricalReplaySimulator()


def get_campaign_terms(campaign_id: str) -> Dict[str, Any]:
    """Retrieve a campaign's configured parameters and rules from BigQuery.

    Returns the campaign's merchant identity, business objective (e.g. ACQUIRE_NEW),
    minimum spend threshold, cashback percentage, cashback cap, budget ceiling,
    redemption limits per customer, and operational status.
    
    Args:
        campaign_id: The unique campaign identifier (e.g., 'CMP131').
        
    Returns:
        A dictionary containing 'campaign_id' and 'terms' record, or an error.
    """
    config = get_config()
    project = config.gcp.project_id
    silver = config.gcp.silver_dataset

    sql = f"""
        SELECT
            campaign_id,
            merchant_id,
            objective,
            min_spend,
            cashback_pct,
            cashback_cap,
            budget,
            funding_type,
            max_redemptions_per_customer,
            status
        FROM `{project}.{silver}.campaigns`
        WHERE campaign_id = @campaign_id
    """
    params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "terms": rows[0] if rows else None,
            "evidence_ref": f"bq:{project}.{silver}.campaigns:{campaign_id}",
        }
    except Exception as exc:
        logger.error(f"Error in get_campaign_terms('{campaign_id}'): {exc}")
        return {
            "success": False,
            "error": f"Failed retrieving campaign terms: {str(exc)}",
            "campaign_id": campaign_id,
            "terms": None,
        }


def get_campaign_performance(campaign_id: str) -> Dict[str, Any]:
    """Retrieve aggregate audience, delivery, redemption, and cashback metrics for a campaign.

    Returns targeted customer count, delivered customer count, awarded redeeming count,
    redemption rate percentage, and total cashback awarded from Gold campaign results.
    
    Args:
        campaign_id: The unique campaign identifier (e.g., 'CMP131').
        
    Returns:
        A dictionary with performance metrics and evidence reference.
    """
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        SELECT
            campaign_id,
            merchant_id,
            targeted_customer_count,
            delivered_customer_count,
            redeeming_customer_count,
            redemption_rate_pct AS redemption_rate,
            cashback_amt_awarded AS cashback_spend,
            posted_txn_count,
            posted_txn_amount
        FROM `{project}.{gold}.gold_campaign_results`
        WHERE campaign_id = @campaign_id
    """
    params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "performance": rows[0] if rows else None,
            "evidence_ref": f"bq:{project}.{gold}.gold_campaign_results:{campaign_id}",
        }
    except Exception as exc:
        logger.error(f"Error in get_campaign_performance('{campaign_id}'): {exc}")
        return {
            "success": False,
            "error": f"Failed retrieving campaign performance: {str(exc)}",
            "campaign_id": campaign_id,
            "performance": None,
        }


def get_spend_distribution(merchant_id: str) -> Dict[str, Any]:
    """Retrieve a merchant's historical transaction profile from BigQuery.

    Returns the merchant's posted transaction count, total posted volume, average
    transaction amount, median transaction amount, and distinct paying customer count.
    
    Args:
        merchant_id: The merchant identifier (e.g., 'M001').
        
    Returns:
        A dictionary with merchant transaction statistics and ticket size distributions.
    """
    config = get_config()
    project = config.gcp.project_id
    gold = config.gcp.gold_dataset

    sql = f"""
        SELECT
            merchant_id,
            merchant_name,
            merchant_category,
            merchant_city,
            posted_txn_count,
            posted_amount_total,
            avg_txn_amount,
            median_txn_amount,
            distinct_customer_count
        FROM `{project}.{gold}.gold_merchant_spend_profile`
        WHERE merchant_id = @merchant_id
    """
    params = [bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id)]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "merchant_id": merchant_id,
            "spend_profile": rows[0] if rows else None,
            "evidence_ref": f"bq:{project}.{gold}.gold_merchant_spend_profile:{merchant_id}",
        }
    except Exception as exc:
        logger.error(f"Error in get_spend_distribution('{merchant_id}'): {exc}")
        return {
            "success": False,
            "error": f"Failed retrieving spend distribution: {str(exc)}",
            "merchant_id": merchant_id,
            "spend_profile": None,
        }


def get_customer_reviews(merchant_id: str, limit: int = 20) -> Dict[str, Any]:
    """Retrieve a merchant's dated customer reviews and ratings from BigQuery.

    Returns up to 'limit' newest reviews, including review ID, date, rating, review text,
    and source reference.
    
    Args:
        merchant_id: The merchant identifier (e.g., 'M001').
        limit: Maximum number of recent reviews to fetch (default: 20).
        
    Returns:
        A dictionary containing merchant_id, reviews array with review IDs, and total retrieved.
    """
    config = get_config()
    project = config.gcp.project_id
    silver = config.gcp.silver_dataset
    bronze = config.gcp.bronze_dataset

    sql = f"""
        SELECT
            review_id,
            merchant_id,
            review_date,
            rating,
            review_text,
            source_ref
        FROM `{project}.{silver}.customer_reviews`
        WHERE merchant_id = @merchant_id
        ORDER BY review_date DESC
        LIMIT @limit
    """
    params = [
        bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "merchant_id": merchant_id,
            "count": len(rows),
            "reviews": rows,
            "evidence_ref": f"bq:{project}.{silver}.customer_reviews:{merchant_id}",
        }
    except Exception as exc:
        logger.warning(f"Silver review query failed, checking bronze fallback: {exc}")
        fallback_sql = f"""
            SELECT review_id, merchant_id, review_date, rating, review_text, source_ref
            FROM `{project}.{bronze}.customer_reviews_raw`
            WHERE merchant_id = @merchant_id
            LIMIT @limit
        """
        try:
            fallback_rows = bq_client.execute_query(fallback_sql, parameters=params)
            return {
                "success": True,
                "merchant_id": merchant_id,
                "count": len(fallback_rows),
                "reviews": fallback_rows,
                "evidence_ref": f"bq:{project}.{bronze}.customer_reviews_raw:{merchant_id}",
            }
        except Exception as inner_exc:
            return {
                "success": False,
                "error": f"Failed retrieving customer reviews: {str(inner_exc)}",
                "merchant_id": merchant_id,
                "reviews": [],
            }


def get_merchant_feedback(merchant_id: str, limit: int = 20) -> Dict[str, Any]:
    """Retrieve dated merchant relationship feedback and operational incident notes.

    Returns recorded notes (e.g., store closure, renovation, staffing changes),
    including feedback ID, event date, verification status, and source reference.
    
    Args:
        merchant_id: The merchant identifier (e.g., 'M001').
        limit: Maximum number of notes to retrieve (default: 20).
        
    Returns:
        A dictionary containing merchant_id, feedback notes array, and provenance metadata.
    """
    config = get_config()
    project = config.gcp.project_id
    silver = config.gcp.silver_dataset
    bronze = config.gcp.bronze_dataset

    sql = f"""
        SELECT
            feedback_id,
            merchant_id,
            event_date,
            feedback_text,
            source_ref,
            verification_status
        FROM `{project}.{silver}.merchant_feedback`
        WHERE merchant_id = @merchant_id
        ORDER BY event_date DESC
        LIMIT @limit
    """
    params = [
        bigquery.ScalarQueryParameter("merchant_id", "STRING", merchant_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "merchant_id": merchant_id,
            "count": len(rows),
            "feedback": rows,
            "evidence_ref": f"bq:{project}.{silver}.merchant_feedback:{merchant_id}",
        }
    except Exception as exc:
        logger.warning(f"Silver feedback query failed, checking bronze fallback: {exc}")
        fallback_sql = f"""
            SELECT feedback_id, merchant_id, event_date, feedback_text, source_ref, verification_status
            FROM `{project}.{bronze}.merchant_feedback_raw`
            WHERE merchant_id = @merchant_id
            LIMIT @limit
        """
        try:
            fallback_rows = bq_client.execute_query(fallback_sql, parameters=params)
            return {
                "success": True,
                "merchant_id": merchant_id,
                "count": len(fallback_rows),
                "feedback": fallback_rows,
                "evidence_ref": f"bq:{project}.{bronze}.merchant_feedback_raw:{merchant_id}",
            }
        except Exception as inner_exc:
            return {
                "success": False,
                "error": f"Failed retrieving merchant feedback: {str(inner_exc)}",
                "merchant_id": merchant_id,
                "feedback": [],
            }


def get_delivery_metrics(campaign_id: str) -> Dict[str, Any]:
    """Retrieve communication delivery statistics and customer-merchant city alignment.

    Calculates total notifications sent, successfully delivered audience, failed sends,
    delivery success rate percentage, and percentage of targeted customers living in a different
    city than the merchant outlet.
    
    Args:
        campaign_id: The unique campaign identifier (e.g., 'CMP131').
        
    Returns:
        A dictionary with send counts, delivery rate, and city mismatch percentages.
    """
    config = get_config()
    project = config.gcp.project_id
    silver = config.gcp.silver_dataset

    sql = f"""
        WITH send_stats AS (
            SELECT
                s.campaign_id,
                COUNT(1) AS total_sends,
                COUNT(DISTINCT s.customer_id) AS targeted_customers,
                COUNT(DISTINCT CASE WHEN UPPER(s.delivery_status) = 'DELIVERED' THEN s.customer_id END) AS delivered_customers,
                COUNT(DISTINCT CASE WHEN UPPER(s.delivery_status) != 'DELIVERED' THEN s.customer_id END) AS failed_deliveries,
                COUNT(DISTINCT CASE WHEN UPPER(COALESCE(c.city, '')) != UPPER(COALESCE(m.city, '')) THEN s.customer_id END) AS out_of_city_customers
            FROM `{project}.{silver}.offer_sends` s
            JOIN `{project}.{silver}.campaigns` cmp ON cmp.campaign_id = s.campaign_id
            JOIN `{project}.{silver}.merchants` m ON m.merchant_id = cmp.merchant_id
            LEFT JOIN `{project}.{silver}.customers` c ON c.customer_id = s.customer_id
            WHERE s.campaign_id = @campaign_id
            GROUP BY s.campaign_id
        )
        SELECT
            campaign_id,
            total_sends,
            targeted_customers,
            delivered_customers,
            failed_deliveries,
            ROUND(SAFE_DIVIDE(delivered_customers, targeted_customers) * 100, 2) AS delivery_rate_pct,
            out_of_city_customers,
            ROUND(SAFE_DIVIDE(out_of_city_customers, targeted_customers) * 100, 2) AS city_mismatch_pct
        FROM send_stats
    """
    params = [bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id)]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "delivery_metrics": rows[0] if rows else None,
            "evidence_ref": f"bq:{project}.{silver}.offer_sends:{campaign_id}",
        }
    except Exception as exc:
        logger.error(f"Error in get_delivery_metrics('{campaign_id}'): {exc}")
        return {
            "success": False,
            "error": f"Failed retrieving delivery metrics: {str(exc)}",
            "campaign_id": campaign_id,
            "delivery_metrics": None,
        }


def get_comparable_campaigns(campaign_id: str, limit: int = 5) -> Dict[str, Any]:
    """Retrieve benchmark redemption performance from peer campaigns in the same merchant category.

    Returns peer campaigns with their merchant name, category, city, spend thresholds,
    cashback percentage, and achieved redemption rate for comparative baseline evaluation.
    
    Args:
        campaign_id: The subject campaign identifier to benchmark against peers.
        limit: Maximum number of peer campaigns to retrieve (default: 5).
        
    Returns:
        A dictionary with category benchmarking rows.
    """
    config = get_config()
    project = config.gcp.project_id
    silver = config.gcp.silver_dataset
    gold = config.gcp.gold_dataset

    sql = f"""
        SELECT
            cr.campaign_id,
            cr.merchant_id,
            m.name AS merchant_name,
            m.category AS merchant_category,
            m.city AS merchant_city,
            c.min_spend,
            c.cashback_pct,
            c.cashback_cap,
            cr.redemption_rate_pct AS redemption_rate
        FROM `{project}.{gold}.gold_campaign_results` cr
        JOIN `{project}.{silver}.campaigns` c ON c.campaign_id = cr.campaign_id
        JOIN `{project}.{silver}.merchants` m ON m.merchant_id = cr.merchant_id
        WHERE m.category = (
            SELECT m2.category
            FROM `{project}.{silver}.campaigns` c2
            JOIN `{project}.{silver}.merchants` m2 ON m2.merchant_id = c2.merchant_id
            WHERE c2.campaign_id = @campaign_id
        )
        AND cr.campaign_id != @campaign_id
        ORDER BY cr.redemption_rate_pct DESC
        LIMIT @limit
    """
    params = [
        bigquery.ScalarQueryParameter("campaign_id", "STRING", campaign_id),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]
    try:
        rows = bq_client.execute_query(sql, parameters=params)
        return {
            "success": True,
            "campaign_id": campaign_id,
            "peer_campaigns": rows,
            "count": len(rows),
            "evidence_ref": f"bq:{project}.{gold}.gold_campaign_results:category_peers",
        }
    except Exception as exc:
        logger.error(f"Error in get_comparable_campaigns('{campaign_id}'): {exc}")
        return {
            "success": False,
            "error": f"Failed retrieving comparable campaigns: {str(exc)}",
            "campaign_id": campaign_id,
            "peer_campaigns": [],
        }


def simulate_campaign_change(campaign_id: str, min_spend: float) -> Dict[str, Any]:
    """Replay proposed minimum spend against targeted historical transactions (retrospective only).

    Evaluates retrospective eligibility on observed bank-card payments of targeted customers.
    Does NOT predict future customer behavior or incremental revenue.
    
    Args:
        campaign_id: The campaign identifier to simulate.
        min_spend: The proposed minimum spend threshold in currency units (e.g., 1000, 1500).
        
    Returns:
        A dictionary with simulation deltas, customer counts, cashback liabilities, and budget check.
    """
    return _SIMULATOR.simulate(campaign_id=campaign_id, proposed_min_spend=min_spend)
