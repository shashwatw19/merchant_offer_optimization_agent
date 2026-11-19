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

BATCH_ID="B$(TZ=Asia/Kolkata date +%d%H%M%S 2>/dev/null || date +%d%H%M%S)"
INGESTION_TS=$(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || date '+%Y-%m-%d %H:%M:%S')

echo "======================================"
echo "Running Bronze Layer Load"
echo "Project      : $PROJECT_ID"
echo "Location     : $LOCATION"
echo "Batch ID     : $BATCH_ID"
echo "Ingestion TS : $INGESTION_TS"
if [ "$IS_DRY_RUN" = true ]; then
    echo "Mode         : DRY-RUN (Syntax & Cost Validation, No Tables Modified)"
fi
echo "======================================"

for file in "$PROJECT_ROOT"/sql/bronze/*.sql
do
    filename=$(basename "$file")
    echo "Executing $filename"

    bq query \
        $DRY_RUN_FLAG \
        --project_id="$PROJECT_ID" \
        --location="$LOCATION" \
        --use_legacy_sql=false \
        --parameter=batch_id::"$BATCH_ID" \
        --parameter=ingestion_ts::"$INGESTION_TS" \
        < "$file"

    echo "Completed $filename"
done

echo "All Bronze loads completed successfully."
