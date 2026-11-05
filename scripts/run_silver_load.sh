#!/bin/bash

set -e

PROJECT_ID="prj-imp-act-campaign"
LOCATION="asia-south1"


echo "======================================"
echo "Running Silver Layer Load"
echo "======================================"

for file in ../sql/silver/*.sql
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