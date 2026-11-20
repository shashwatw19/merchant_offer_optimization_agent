#!/usr/bin/env bash
# ==============================================================================
# run_all.sh
# Master End-to-End Orchestrator for Merchant Offer Optimization Agent
# Unifies BATCH_ID and IST timezone across Bronze, Silver, Gold (Alerts) & Agent
# ==============================================================================
set -e

export TZ="Asia/Kolkata"
export BATCH_ID="B_$(date +'%y%m%d_%H%M')"
RUN_START_IST=$(date +"%Y-%m-%d %H:%M:%S IST")

echo "=========================================================="
echo " Starting End-to-End Campaign Ingestion & AI Agent Flow   "
echo " Unified Batch ID : ${BATCH_ID}                           "
echo " Started At (IST) : ${RUN_START_IST}                      "
echo "=========================================================="

# Step 1: Initialize Setup Datasets & Watermark tables
echo "--> Step 1/5: Initializing BigQuery Datasets & Watermarks..."
PROJECT_ID="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"

bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < sql/setup/00_create_datasets.sql
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < sql/setup/01_create_watermark_tables.sql
bq query --project_id="$PROJECT_ID" --location="$LOCATION" --use_legacy_sql=false < sql/dq/01_rejected_records.sql

# Step 2: Bronze Ingestion
echo "--> Step 2/5: Ingesting Bronze Layer..."
bash scripts/run_bronze.sh

# Step 3: Silver Cleansing & BR-4 Conservation
echo "--> Step 3/5: Transforming Silver Layer & Quarantining Rejections..."
bash scripts/run_silver.sh

# Step 4: Gold Marts & Direct Alert Generation
echo "--> Step 4/5: Calculating Gold Marts & DIRECT Alert Generation..."
bash scripts/run_gold.sh

# Step 5: Autonomous AI Investigation Agent Batch
echo "--> Step 5/5: Launching Autonomous Cognitive Investigation Agent Batch..."
bash scripts/run_agent.sh

RUN_END_IST=$(date +"%Y-%m-%d %H:%M:%S IST")
echo "=========================================================="
echo " End-to-End Run Complete for Batch: ${BATCH_ID}           "
echo " Finished At (IST): ${RUN_END_IST}                        "
echo "=========================================================="
