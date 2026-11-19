#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

DRY_RUN_DESC=""
for arg in "$@"; do
    if [ "$arg" == "--dry-run" ] || [ "$arg" == "-d" ]; then
        DRY_RUN_DESC=" [DRY-RUN MODE]"
    fi
done

echo "======================================"
echo "Starting Complete ETL Pipeline$DRY_RUN_DESC"
echo "======================================"

echo ""
echo "Step 1: Running Bronze Layer..."
bash "$SCRIPT_DIR/run_bronze_load.sh" "$@"

echo ""
echo "Step 2: Running Silver Layer..."
bash "$SCRIPT_DIR/run_silver_load.sh" "$@"

echo ""
echo "Step 3: Running Gold Layer..."
bash "$SCRIPT_DIR/run_gold_load.sh" "$@"

echo ""
echo "======================================"
echo "ETL Pipeline Completed Successfully$DRY_RUN_DESC"
echo "======================================"
