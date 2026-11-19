#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ensure Google Cloud SDK uses available Python interpreter in Git Bash / Windows
if [ -z "$CLOUDSDK_PYTHON" ]; then
    if command -v python &>/dev/null; then
        export CLOUDSDK_PYTHON="python"
    elif command -v python3 &>/dev/null; then
        export CLOUDSDK_PYTHON="python3"
    elif command -v py &>/dev/null; then
        export CLOUDSDK_PYTHON="py"
    fi
fi

PROJECT_ID="${GCP_PROJECT:-prj-imp-act-campaign}"
LOCATION="${BQ_LOCATION:-asia-south1}"

DRY_RUN_FLAG=""
IS_DRY_RUN=false
for arg in "$@"; do
    if [ "$arg" == "--dry-run" ] || [ "$arg" == "-d" ]; then
        DRY_RUN_FLAG="--dry_run"
        IS_DRY_RUN=true
    fi
done

echo "======================================"
echo "Running Silver Layer Load"
echo "Project      : $PROJECT_ID"
echo "Location     : $LOCATION"
if [ "$IS_DRY_RUN" = true ]; then
    echo "Mode         : DRY-RUN (Syntax & Cost Validation, No Tables Modified)"
fi
echo "======================================"

# Ordered dependency sequence to respect Foreign Key integrity:
# 1. Error Quarantine Table
# 2. Independent Dimensions (customers, merchants)
# 3. Direct References (campaigns, transactions, customer_reviews, merchant_feedback)
# 4. Campaign Sends
# 5. Campaign Redemptions (depends on transactions, campaigns, customers)
SILVER_FILES=(
    "invalid_records.sql"
    "merchants.sql"
    "customers.sql"
    "campaigns.sql"
    "transactions.sql"
    "customer_reviews.sql"
    "merchant_feedback.sql"
    "offer_sends.sql"
    "offer_redemptions.sql"
)

for sql_name in "${SILVER_FILES[@]}"
do
    file="$PROJECT_ROOT/sql/silver/$sql_name"
    if [ -f "$file" ]; then
        echo "Executing $sql_name"

        bq query \
            $DRY_RUN_FLAG \
            --project_id="$PROJECT_ID" \
            --location="$LOCATION" \
            --use_legacy_sql=false \
            < "$file"

        echo "Completed $sql_name"
    else
        echo "Warning: $file not found, skipping"
    fi
done

echo "All Silver loads completed successfully."
