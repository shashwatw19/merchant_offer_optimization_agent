#!/bin/bash

set -e

echo "======================================"
echo "Starting Complete ETL Pipeline"
echo "======================================"

echo ""
echo "Step 1: Running Bronze Layer..."
bash scripts/run_bronze_load.sh

echo ""
echo "Step 2: Running Silver Layer..."
bash scripts/run_silver_load.sh

echo ""
echo "Step 3: Running Gold Layer..."
bash scripts/run_gold_load.sh

echo ""
echo "======================================"
echo "ETL Pipeline Completed Successfully"
echo "======================================"