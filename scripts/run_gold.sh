#!/usr/bin/env bash
# ==============================================================================
# run_gold.sh
# End-to-End Gold Dataset Builder & Direct Alert Generator
# Syncs rule_config, builds marts, and directly outputs offers_gold.alerts
# ==============================================================================
set -e
export TZ="Asia/Kolkata"

if [ -z "$BATCH_ID" ]; then
  BATCH_ID="B_$(date +'%y%m%d_%H%M')"
fi

GOLD_START_IST=$(date +"%Y-%m-%d %H:%M:%S IST")
echo "=========================================================="
echo " Building Gold Layer & Generating Alerts directly in Gold  "
echo " Batch ID: ${BATCH_ID} (${GOLD_START_IST})                "
echo "=========================================================="

PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"

# 1. Ensure offers_gold schema exists
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false "CREATE SCHEMA IF NOT EXISTS offers_gold;"

# 2. Build Gold Campaign Results & Profiles
echo "--> Building offers_gold.gold_campaign_results..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter="batch_id:STRING:${BATCH_ID}" < sql/gold/gold_campaign_results.sql

echo "--> Building offers_gold.gold_campaign_profile..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter="batch_id:STRING:${BATCH_ID}" < sql/gold/gold_campaign_profile.sql

echo "--> Building offers_gold.gold_merchant_spend_profile..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter="batch_id:STRING:${BATCH_ID}" < sql/gold/gold_merchant_weekly.sql

# 3. Seed / Sync Rule Configuration from config/rule_config.csv
echo "--> Syncing offers_gold.rule_config from config/rule_config.csv..."
if [ -s "config/rule_config.csv" ]; then
  python sql/gold/load_rule_config.py --csv_path "config/rule_config.csv" --batch_id "${BATCH_ID}"
else
  bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < sql/gold/04_seed_rule_config.sql
fi

# 4. DIRECT ALERT GENERATION (Coupled with Gold)
echo "--> DIRECT ALERT GENERATION: Evaluating R1, R2, R3 and writing to offers_gold.alerts..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false --parameter="batch_id:STRING:${BATCH_ID}" < sql/gold/08_generate_alerts.sql

# 5. Data Quality & Reconciliation
echo "--> Running BR-4 Data Quality & Reconciliation..."
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < sql/dq/02_dq_reconciliation.sql

GOLD_END_IST=$(date +"%Y-%m-%d %H:%M:%S IST")
echo "=========================================================="
echo " Gold Layer & Alert Generation Finished: ${GOLD_END_IST}   "
echo "=========================================================="
