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
echo "Running Gold Layer Load"
echo "Project      : $PROJECT_ID"
echo "Location     : $LOCATION"
if [ "$IS_DRY_RUN" = true ]; then
    echo "Mode         : DRY-RUN (Syntax & Cost Validation, No Tables Modified)"
fi
echo "======================================"

for file in "$PROJECT_ROOT"/sql/gold/*.sql
do
    filename=$(basename "$file")
    echo "Executing $filename"

    bq query \
        $DRY_RUN_FLAG \
        --project_id="$PROJECT_ID" \
        --location="$LOCATION" \
        --use_legacy_sql=false \
        < "$file"

    echo "Completed $filename"
done

echo "All Gold loads completed successfully."
