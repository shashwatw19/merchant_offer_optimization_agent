"""Merchant Offer table catalog and question-aware schema context."""

from typing import Dict, List, Optional, Set

from analytics.models import ColumnMetadata, TableMetadata


def Col(name: str, data_type: str, description: str) -> ColumnMetadata:
    """Compact structured column definition."""
    return ColumnMetadata(name=name, data_type=data_type, description=description)


def _columns(spec: str) -> List[ColumnMetadata]:
    """Compatibility helper to parse ``name:type:description`` lines."""
    result: List[ColumnMetadata] = []
    for line in spec.strip().splitlines():
        name, data_type, description = line.split("|", 2)
        result.append(Col(name=name, data_type=data_type, description=description))
    return result


BUILTIN_TABLE_CATALOG: Dict[str, TableMetadata] = {
    "offers_gold.gold_campaign_results": TableMetadata(
        table_id="gold_campaign_results",
        dataset_id="offers_gold",
        full_table_name="offers_gold.gold_campaign_results",
        business_name="Campaign Performance",
        description="Campaign delivery, redemption, cashback, and posted transaction measures.",
        business_synonyms=["campaign results", "campaign performance", "redemption rate", "cashback"],
        columns=[
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("measurement_start_date", "DATETIME", "Beginning of the measurement period"),
            Col("measurement_end_date", "DATETIME", "End of the measurement period"),
            Col("targeted_customer_count", "INT64", "Customers targeted"),
            Col("delivered_customer_count", "INT64", "Customers successfully delivered an offer"),
            Col("redeeming_customer_count", "INT64", "Customers who redeemed an offer"),
            Col("redemption_rate_pct", "NUMERIC", "Redemption rate percentage"),
            Col("cashback_amt_awarded", "NUMERIC", "Cashback awarded"),
            Col("posted_txn_count", "INT64", "Posted transaction count"),
            Col("posted_txn_amount", "NUMERIC", "Posted transaction amount"),
            Col("campaign_status", "STRING", "Campaign status"),
            Col("quality_flag", "STRING", "Data quality flag"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingestion_time", "DATETIME", "Ingestion timestamp"),
        ],
        common_joins=["gold_campaign_results.campaign_id = campaigns.campaign_id"],
    ),
    "offers_gold.gold_campaign_profile": TableMetadata(
        table_id="gold_campaign_profile",
        dataset_id="offers_gold",
        full_table_name="offers_gold.gold_campaign_profile",
        business_name="Campaign Profile",
        description="Campaign terms joined with merchant name, category, and location.",
        business_synonyms=["campaign profile", "campaign terms", "campaign rules", "offer details"],
        columns=[
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("merchant_name", "STRING", "Merchant name"),
            Col("merchant_category", "STRING", "Merchant category"),
            Col("merchant_city", "STRING", "Merchant city"),
            Col("objective", "STRING", "Campaign objective"),
            Col("cmp_start_date", "DATETIME", "Campaign start date"),
            Col("cmp_end_date", "DATETIME", "Campaign end date"),
            Col("min_spend", "NUMERIC", "Minimum spend required"),
            Col("cashback_pct", "NUMERIC", "Cashback percentage"),
            Col("cashback_cap", "NUMERIC", "Maximum cashback amount"),
            Col("budget", "NUMERIC", "Campaign budget"),
            Col("funding_type", "STRING", "Campaign funding type"),
            Col("max_redemptions_per_customer", "INT64", "Maximum redemptions per customer"),
            Col("campaign_status", "STRING", "Campaign status"),
            Col("quality_flag", "STRING", "Data quality flag"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingestion_time", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_gold.gold_merchant_spend_profile": TableMetadata(
        table_id="gold_merchant_spend_profile",
        dataset_id="offers_gold",
        full_table_name="offers_gold.gold_merchant_spend_profile",
        business_name="Merchant Spend Profile",
        description="Weekly merchant transaction volume, ticket size, and customer counts.",
        business_synonyms=["merchant spend", "merchant revenue", "average ticket", "ticket size", "sales"],
        columns=[
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("merchant_name", "STRING", "Merchant name"),
            Col("merchant_category", "STRING", "Merchant category"),
            Col("merchant_city", "STRING", "Merchant city"),
            Col("period_start", "DATETIME", "Beginning of the reporting period"),
            Col("period_end", "DATETIME", "End of the reporting period"),
            Col("posted_txn_count", "INT64", "Posted transaction count"),
            Col("posted_amount_total", "NUMERIC", "Total posted transaction amount"),
            Col("avg_txn_amount", "NUMERIC", "Average transaction amount"),
            Col("median_txn_amount", "NUMERIC", "Median transaction amount"),
            Col("distinct_customer_count", "INT64", "Distinct transacting customers"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingestion_time", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_gold.alerts": TableMetadata(
        table_id="alerts",
        dataset_id="offers_gold",
        full_table_name="offers_gold.alerts",
        business_name="Campaign Alerts",
        description="Rule-triggered campaign performance alerts and their resolution status.",
        business_synonyms=["alert", "alerts", "rule violation", "campaign issue"],
        columns=[
            Col("alert_id", "STRING", "Alert identifier"),
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("rule_id", "STRING", "Triggered rule identifier"),
            Col("metric_name", "STRING", "Name of the measured metric"),
            Col("metric_value", "NUMERIC", "Observed metric value"),
            Col("threshold_value", "NUMERIC", "Configured threshold"),
            Col("status", "STRING", "Alert status"),
            Col("created_at", "TIMESTAMP", "Alert creation time"),
            Col("resolved_at", "TIMESTAMP", "Alert resolution time"),
            Col("summary", "STRING", "Alert summary"),
            Col("investigation_summary", "STRING", "Investigation summary"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
        ],
    ),
    "offers_gold.rule_config": TableMetadata(
        table_id="rule_config",
        dataset_id="offers_gold",
        full_table_name="offers_gold.rule_config",
        business_name="Alert Rule Configuration",
        description="Configured thresholds for campaign monitoring rules.",
        business_synonyms=["rule config", "rule threshold", "threshold", "policy"],
        columns=[
            Col("rule_id", "STRING", "Rule identifier"),
            Col("parameter", "STRING", "Parameter name"),
            Col("value", "NUMERIC", "Configured parameter value"),
            Col("description", "STRING", "Parameter description"),
            Col("updated_at", "TIMESTAMP", "Last update time"),
        ],
    ),
    "offers_silver.campaigns": TableMetadata(
        table_id="campaigns",
        dataset_id="offers_silver",
        full_table_name="offers_silver.campaigns",
        business_name="Campaigns",
        description="Normalized campaign definitions and offer terms.",
        business_synonyms=["campaign", "campaigns", "offer", "offers"],
        columns=[
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("objective", "STRING", "Campaign objective"),
            Col("start_date", "DATE", "Campaign start date"),
            Col("end_date", "DATE", "Campaign end date"),
            Col("min_spend", "NUMERIC", "Minimum spend required"),
            Col("cashback_pct", "NUMERIC", "Cashback percentage"),
            Col("cashback_cap", "NUMERIC", "Maximum cashback amount"),
            Col("budget", "NUMERIC", "Campaign budget"),
            Col("funding_type", "STRING", "Campaign funding type"),
            Col("max_redemptions_per_customer", "INT64", "Maximum redemptions per customer"),
            Col("status", "STRING", "Campaign status"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
        common_joins=["campaigns.merchant_id = merchants.merchant_id"],
    ),
    "offers_silver.merchants": TableMetadata(
        table_id="merchants",
        dataset_id="offers_silver",
        full_table_name="offers_silver.merchants",
        business_name="Merchants",
        description="Normalized merchant identity, category, city, and status.",
        business_synonyms=["merchant", "merchants", "store", "retailer", "vendor"],
        columns=[
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("name", "STRING", "Merchant name"),
            Col("category", "STRING", "Merchant category"),
            Col("city", "STRING", "Merchant city"),
            Col("status", "STRING", "Merchant status"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.customers": TableMetadata(
        table_id="customers",
        dataset_id="offers_silver",
        full_table_name="offers_silver.customers",
        business_name="Customers",
        description="Customer segment and marketing eligibility fields. No name or card-number fields.",
        business_synonyms=["customer", "customers", "cardholder", "client"],
        columns=[
            Col("customer_id", "STRING", "Customer identifier"),
            Col("city", "STRING", "Customer city"),
            Col("segment", "STRING", "Customer segment"),
            Col("marketing_eligible", "BOOL", "Whether the customer is eligible for marketing"),
            Col("card_status", "STRING", "Card status"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.transactions": TableMetadata(
        table_id="transactions",
        dataset_id="offers_silver",
        full_table_name="offers_silver.transactions",
        business_name="Transactions",
        description="Normalized customer-to-merchant transactions.",
        business_synonyms=["transaction", "transactions", "purchase", "purchases", "spend"],
        columns=[
            Col("txn_id", "STRING", "Transaction identifier"),
            Col("customer_id", "STRING", "Customer identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("txn_ts", "DATETIME", "Transaction timestamp"),
            Col("amount", "NUMERIC", "Transaction amount"),
            Col("txn_status", "STRING", "Transaction status"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.offer_sends": TableMetadata(
        table_id="offer_sends",
        dataset_id="offers_silver",
        full_table_name="offers_silver.offer_sends",
        business_name="Offer Sends",
        description="Offer delivery attempts and delivery status by customer.",
        business_synonyms=["offer sends", "delivery", "delivered offers", "campaign reach"],
        columns=[
            Col("send_id", "STRING", "Send identifier"),
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("customer_id", "STRING", "Customer identifier"),
            Col("sent_at", "DATETIME", "Send timestamp"),
            Col("delivery_status", "STRING", "Delivery status"),
            Col("channel", "STRING", "Delivery channel"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.offer_redemptions": TableMetadata(
        table_id="offer_redemptions",
        dataset_id="offers_silver",
        full_table_name="offers_silver.offer_redemptions",
        business_name="Offer Redemptions",
        description="Customer redemptions and awarded cashback for campaigns.",
        business_synonyms=["redemption", "redemptions", "redeemed", "cashback awarded"],
        columns=[
            Col("redemption_id", "STRING", "Redemption identifier"),
            Col("txn_id", "STRING", "Transaction identifier"),
            Col("campaign_id", "STRING", "Campaign identifier"),
            Col("customer_id", "STRING", "Customer identifier"),
            Col("awarded_cashback", "NUMERIC", "Cashback awarded"),
            Col("status", "STRING", "Redemption status"),
            Col("awarded_at", "DATETIME", "Award timestamp"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.customer_reviews": TableMetadata(
        table_id="customer_reviews",
        dataset_id="offers_silver",
        full_table_name="offers_silver.customer_reviews",
        business_name="Customer Reviews",
        description="Customer ratings and review text associated with merchants.",
        business_synonyms=["review", "reviews", "rating", "ratings", "customer feedback"],
        columns=[
            Col("review_id", "STRING", "Review identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("review_date", "DATE", "Review date"),
            Col("collected_at", "DATETIME", "Collection timestamp"),
            Col("rating", "NUMERIC", "Customer rating"),
            Col("review_text", "STRING", "Review text"),
            Col("source_ref", "STRING", "Source reference"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.merchant_feedback": TableMetadata(
        table_id="merchant_feedback",
        dataset_id="offers_silver",
        full_table_name="offers_silver.merchant_feedback",
        business_name="Merchant Feedback",
        description="Feedback events recorded for merchants.",
        business_synonyms=["merchant feedback", "merchant complaint"],
        columns=[
            Col("feedback_id", "STRING", "Feedback identifier"),
            Col("merchant_id", "STRING", "Merchant identifier"),
            Col("event_date", "DATE", "Event date"),
            Col("recorded_at", "DATETIME", "Recording timestamp"),
            Col("feedback_text", "STRING", "Feedback text"),
            Col("source_ref", "STRING", "Source reference"),
            Col("verification_status", "STRING", "Verification status"),
            Col("batch_id", "STRING", "Ingestion batch identifier"),
            Col("ingested_at", "DATETIME", "Ingestion timestamp"),
        ],
    ),
    "offers_silver.city_master": TableMetadata(
        table_id="city_master",
        dataset_id="offers_silver",
        full_table_name="offers_silver.city_master",
        business_name="City Master",
        description="Canonical city names.",
        business_synonyms=["city master", "standard city"],
        columns=[
            Col("city_id", "STRING", "City identifier"),
            Col("city_standard_name", "STRING", "Canonical city name"),
        ],
    ),
    "offers_silver.city_mapping": TableMetadata(
        table_id="city_mapping",
        dataset_id="offers_silver",
        full_table_name="offers_silver.city_mapping",
        business_name="City Mapping",
        description="Source city names mapped to canonical city identifiers.",
        business_synonyms=["city mapping", "city alias"],
        columns=[
            Col("city_id", "STRING", "City identifier"),
            Col("city_name", "STRING", "Source city name"),
        ],
    ),
}


class MetadataCatalog:
    """Provides business synonym lookup and schema context for SQL generation."""

    def __init__(self, custom_tables: Optional[Dict[str, TableMetadata]] = None):
        self.tables = custom_tables or BUILTIN_TABLE_CATALOG.copy()
        self._synonym_index: Dict[str, Set[str]] = {}
        for table_name, metadata in self.tables.items():
            for synonym in metadata.business_synonyms:
                self._synonym_index.setdefault(synonym.lower().strip(), set()).add(table_name)

    def find_relevant_tables(self, question: str) -> List[TableMetadata]:
        question_lower = question.lower()
        matched: Set[str] = set()
        for synonym, tables in self._synonym_index.items():
            if synonym and synonym in question_lower:
                matched.update(tables)
        for table_name, metadata in self.tables.items():
            if metadata.table_id.lower() in question_lower:
                matched.add(table_name)
            for column in metadata.columns:
                if column.name.lower() in question_lower:
                    matched.add(table_name)
        if not matched:
            matched = {
                "offers_gold.gold_campaign_results",
                "offers_gold.gold_merchant_spend_profile",
                "offers_gold.alerts",
                "offers_silver.campaigns",
            }
        return [self.tables[name] for name in sorted(matched) if name in self.tables]

    def get_schema_prompt_context(self, question: Optional[str] = None) -> str:
        target = self.find_relevant_tables(question) if question else list(self.tables.values())
        lines = ["AVAILABLE BIGQUERY TABLES AND COLUMNS:"]
        for table in target:
            lines.extend(
                [
                    f"\nTable: `{table.full_table_name}` ({table.business_name})",
                    f"Description: {table.description}",
                    "Columns:",
                ]
            )
            for column in table.columns:
                lines.append(f"- {column.name} ({column.data_type}): {column.description}")
            if table.common_joins:
                lines.append("Common joins:")
                lines.extend(f"- {join}" for join in table.common_joins)
        return "\n".join(lines)


_metadata_catalog: Optional[MetadataCatalog] = None


def get_metadata_catalog() -> MetadataCatalog:
    global _metadata_catalog
    if _metadata_catalog is None:
        _metadata_catalog = MetadataCatalog()
    return _metadata_catalog
