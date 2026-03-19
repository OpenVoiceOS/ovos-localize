#!/bin/bash
# launch.sh - Automation script for OVOS Localize

# 1. Sync dependencies
echo "--- Syncing dependencies with uv ---"
uv sync --extra dev

# 2. Generate Data
echo ""
echo "--- Generating Skill Data (Front-end JSONs) ---"
uv run python scripts/generate_data.py

# 3. Generate ML Datasets
echo ""
echo "--- Generating Open Data (ML Datasets) ---"
uv run python scripts/generate_datasets.py

# 4. Serve the SPA
echo ""
echo "--- Starting local server at http://localhost:8000 ---"
echo "Press Ctrl+C to stop."
uv run python -m http.server 8000
