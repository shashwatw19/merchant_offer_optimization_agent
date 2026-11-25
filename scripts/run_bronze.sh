#!/usr/bin/env bash
set -e

# =====================================================================
# run_bronze.sh
# Incremental Delta Ingestion into Bronze Layer (offers_bronze.*)
# Driven by gcs_ingestion_log & pipeline_watermark via WatermarkService
# =====================================================================
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT:${PYTHONPATH:-}"
export GOOGLE_CLOUD_PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
export GCP_PROJECT="${GOOGLE_CLOUD_PROJECT}"
export GOOGLE_CLOUD_LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"
export BQ_LOCATION="${GOOGLE_CLOUD_LOCATION}"

if [ -z "$BATCH_ID" ]; then
  BATCH_ID="B_$(date +'%y%m%d_%H%M')"
fi

LOAD_TIME_IST=$(date +"%Y-%m-%d %H:%M:%S IST")

echo "======================================================"
echo "Starting Incremental Bronze Ingestion (${LOAD_TIME_IST})"
echo "Project        : ${GCP_PROJECT}"
echo "Location       : ${BQ_LOCATION}"
echo "Batch ID       : ${BATCH_ID}"
echo "======================================================"

python -m pipeline.incremental_runner --stage bronze --batch-id "${BATCH_ID}"

echo "=== Incremental Bronze ingestion completed for Batch: ${BATCH_ID} (${LOAD_TIME_IST}) ==="
