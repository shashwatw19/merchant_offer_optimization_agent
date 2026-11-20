#!/usr/bin/env bash
set -e

# =====================================================================
# run_bronze.sh
# Delta Ingestion into Bronze Layer (offers_bronze.*)
# Matches New BFSI architecture: explicit numbered sequence, batch propagation
# =====================================================================
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"

if [ -z "$BATCH_ID" ]; then
  BATCH_ID="B_$(date +'%y%m%d_%H%M')"
fi

LOAD_TIME_IST=$(date +"%Y-%m-%d %H:%M:%S IST")

echo "======================================================"
echo "Starting Bronze Ingestion Run (${LOAD_TIME_IST})"
echo "Project        : ${PROJECT_ID}"
echo "Location       : ${LOCATION}"
echo "Batch ID       : ${BATCH_ID}"
echo "======================================================"

echo "1. Loading merchants..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/merchants_load.sql"

echo "2. Loading customers..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/customers_load.sql"

echo "3. Loading campaigns..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/campaign_load.sql"

echo "4. Loading transactions..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/transactions_load.sql"

echo "5. Loading offer_sends..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/offer_sends_load.sql"

echo "6. Loading offer_redemptions..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/offer_redemptions_load.sql"

echo "7. Loading customer_reviews..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/customer_reviews_load.sql"

echo "8. Loading merchant_feedback..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter=batch_id::"$BATCH_ID" --parameter=ingestion_ts::"$LOAD_TIME_IST" < "$PROJECT_ROOT/sql/bronze/merchant_feedback_load.sql"

echo "=== Bronze Layer ingestion completed successfully for Batch: ${BATCH_ID} (${LOAD_TIME_IST}) ==="
