#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROJECT_ID="${GCP_PROJECT:-prj-imp-act-campaign}"
LOCATION="${BQ_LOCATION:-asia-south1}"

BATCH_ID="B$(TZ=Asia/Kolkata date +%d%H%M%S)"
INGESTION_TS=$(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S')

echo "======================================"
echo "Running Bronze Layer Load"
echo "Project      : $PROJECT_ID"
echo "Location     : $LOCATION"
echo "Batch ID     : $BATCH_ID"
echo "Ingestion TS : $INGESTION_TS"
echo "======================================"

for file in "$PROJECT_ROOT"/sql/bronze/*.sql
do
    echo "Executing $file"

    bq query \
        --project_id="$PROJECT_ID" \
        --location="$LOCATION" \
        --use_legacy_sql=false \
        --parameter=batch_id::"$BATCH_ID" \
        --parameter=ingestion_ts::"$INGESTION_TS" \
        < "$file"

    echo "Completed $file"
done

echo "All Bronze loads completed successfully."
