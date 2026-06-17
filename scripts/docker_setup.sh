#!/bin/bash
# Run once after "docker-compose up -d" to pull the LLM model and load demo data.
set -e

echo "=== BIAT IT Docker Setup ==="
echo ""

echo "[1/3] Waiting for Ollama to be ready..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "Ollama ready."

echo "[2/3] Pulling qwen2.5:3b model (first run: ~2 GB download)..."
docker exec biat_ollama ollama pull qwen2.5:3b
echo "Model ready."

echo "[3/3] Loading demo dataset..."
docker exec biat_billing_app python scripts/make_full_demo_dataset.py
echo "Dataset loaded."

echo ""
echo "========================================="
echo "Setup complete. Open: http://localhost:8501"
echo "Default password: biat2024"
echo "========================================="
