#!/bin/bash
# Share the BIAT IT demo app via ngrok tunnel
# Usage: bash scripts/share_demo.sh
set -e

echo "=== BIAT IT Demo Share ==="

# Check ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "Install ngrok: brew install ngrok"
    echo "Then: ngrok authtoken YOUR_TOKEN"
    exit 1
fi

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Starting Ollama..."
    ollama serve &
    sleep 3
fi

# Start Streamlit in background if not running
if ! curl -s http://localhost:8501/_stcore/health > /dev/null 2>&1; then
    echo "Starting Streamlit..."
    streamlit run app/Home.py &
    sleep 5
fi

echo "Starting ngrok tunnel..."
echo "Share the URL below with your supervisor."
echo "Press Ctrl+C to stop sharing."
echo ""
ngrok http 8501
