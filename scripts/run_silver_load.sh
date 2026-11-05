#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-prj-imp-act-campaign}"
LOCATION="${BQ_LOCATION:-asia-south1}"

echo "======================================"
echo "Running Silver Layer Load"
echo "Project      : $PROJECT_ID"
echo "Location     : $LOCATION"
echo "======================================"

for file in "$PROJECT_ROOT"/sql/silver/*.sql
do
    echo "Executing $file"

    bq query \
        --project_id="$PROJECT_ID" \
        --location="$LOCATION" \
        --use_legacy_sql=false \
        < "$file"

    echo "Completed $file"
done

echo "All Silver loads completed successfully."
