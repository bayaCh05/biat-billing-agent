#!/usr/bin/env python3
"""Start the FastAPI REST layer.

Usage:
    python scripts/run_api.py           # port 8000, auto-reload off
    python scripts/run_api.py --reload  # with hot-reload for development
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path so `api` and `src` are importable
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

if __name__ == "__main__":
    reload = "--reload" in sys.argv
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=reload)
