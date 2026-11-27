#!/usr/bin/env bash
set -e

# =====================================================================
# run_silver.sh
# Executes Silver Layer Reference Tables, Transformations & Quarantines
# Matches New BFSI architecture: explicit numbered sequence, batch propagation
# =====================================================================
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"

# Inherit BATCH_ID from parent run_all.sh, or generate a unified IST token if run independently
if [ -z "$BATCH_ID" ]; then
  BATCH_ID="B_$(date +'%y%m%d_%H%M')"
fi

SILVER_START_IST=$(date +"%Y-%m-%d %H:%M:%S IST")

echo "======================================================"
echo "Starting Silver Layer Processing (${SILVER_START_IST})"
echo "Project        : ${PROJECT_ID}"
echo "Location       : ${LOCATION}"
echo "Batch ID       : ${BATCH_ID}"
echo "======================================================"

# Strict Topological Execution Order (Identical to New BFSI explicit sequence):
# Step 0: merchants.sql creates offers_silver (city master/mapping) and offers_silver.merchants
echo "0. Building offers_silver.merchants & reference tables..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/merchants.sql"

# Step 1: customers.sql uses city mapping and creates offers_silver.customers
echo "1. Building offers_silver.customers..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/customers.sql"

# Step 2: campaigns.sql joins offers_silver.merchants
echo "2. Building offers_silver.campaigns..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/campaigns.sql"

# Step 3: transactions.sql joins customers and merchants
echo "3. Building offers_silver.transactions..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/transactions.sql"

# Step 4: offer_sends.sql joins campaigns and customers
echo "4. Building offers_silver.offer_sends..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/offer_sends.sql"

# Step 5: offer_redemptions.sql joins transactions, campaigns, customers
echo "5. Building offers_silver.offer_redemptions..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/offer_redemptions.sql"

# Step 6: customer_reviews.sql joins merchants
echo "6. Building offers_silver.customer_reviews..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/customer_reviews.sql"

# Step 7: merchant_feedback.sql joins merchants
echo "7. Building offers_silver.merchant_feedback..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < "$PROJECT_ROOT/sql/silver/merchant_feedback.sql"

SILVER_END_IST=$(date +"%Y-%m-%d %H:%M:%S IST")
echo "=== Silver Layer completed successfully for Batch: ${BATCH_ID} at ${SILVER_END_IST} ==="
