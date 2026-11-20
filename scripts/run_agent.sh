#!/usr/bin/env bash
# ==============================================================================
# run_agent.sh
# Autonomous Batch Investigation Runner for Merchant Offer Optimization Agent
# Follows New BFSI architecture: auto-exports PYTHONPATH="src" and GCP variables
# ==============================================================================
set -e
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Ensure PYTHONPATH includes src/ and project root
export PYTHONPATH="$PROJECT_ROOT/src:$PROJECT_ROOT:${PYTHONPATH:-}"

# Ensure GCP environment variables are active
export GOOGLE_CLOUD_PROJECT="${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-prj-imp-act-campaign}}"
export GCP_PROJECT="${GOOGLE_CLOUD_PROJECT}"
export GOOGLE_CLOUD_LOCATION="${BQ_LOCATION:-${GOOGLE_CLOUD_LOCATION:-asia-south1}}"
export BQ_LOCATION="${GOOGLE_CLOUD_LOCATION}"

if [ -z "$BATCH_ID" ]; then
  BATCH_ID="B_$(date +'%y%m%d_%H%M')"
fi

echo "=========================================================="
echo " Launching Cognitive Agent Batch for Batch: ${BATCH_ID}   "
echo " Project : ${GOOGLE_CLOUD_PROJECT}                        "
echo " Region  : ${GOOGLE_CLOUD_LOCATION}                       "
echo "=========================================================="

python -m agents.run_alert_pipeline --batch-id "${BATCH_ID}"
