#!/bin/bash

set -e

PROJECT_ID="prj-imp-act-campaign"
LOCATION="asia-south1"

BATCH_ID="B$(TZ=Asia/Kolkata date +%d%H%M%S)"
INGESTION_TS=$(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S')

echo "======================================"
echo "Running Bronze Layer Load"
echo "Batch ID     : $BATCH_ID"
echo "Ingestion TS : $INGESTION_TS"
echo "======================================"

for file in ../sql/bronze/*.sql
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