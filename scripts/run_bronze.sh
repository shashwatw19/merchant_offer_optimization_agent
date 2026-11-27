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
export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT:${PYTHONPATH:-}"
export GCP_PROJECT="${PROJECT_ID}"
export BQ_LOCATION="${LOCATION}"

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

python -m pipeline.file_tracker --batch-id "${BATCH_ID}"

echo "=== Bronze Layer ingestion completed successfully for Batch: ${BATCH_ID} (${LOAD_TIME_IST}) ==="
