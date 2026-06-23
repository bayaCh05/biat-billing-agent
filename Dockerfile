# ── Stage 1: build React SPA ─────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
# Empty VITE_API_URL → client uses relative /api paths (same-origin in container)
RUN VITE_API_URL= npm run build


# ── Stage 2: Python API + static files ───────────────────────────────────────
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-ara \
    libpoppler-cpp-dev \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libmagic1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 biatit

WORKDIR /app

COPY pyproject.toml ./
RUN python3 -c "import tomllib,subprocess,sys; d=tomllib.load(open('pyproject.toml','rb')); deps=d['project']['dependencies']+d['project']['optional-dependencies']['dev']; subprocess.run([sys.executable,'-m','pip','install','--no-cache-dir']+deps,check=True)"

COPY . .
RUN pip install --no-cache-dir --no-deps -e .

# Inject the compiled SPA from stage 1
COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN mkdir -p data exports invoices uploads inbox logs \
    && chown -R biatit:biatit /app

USER biatit

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s \
    --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

ENTRYPOINT ["sh", "-c", \
    "python -c \"\
from src.storage.db import build_engine, init_db; \
import os; \
db_url = os.environ.get('DATABASE_URL', 'sqlite:////app/data/invoices.db'); \
engine = build_engine(db_url); \
init_db(engine); \
print('Database initialised.')\" \
&& uvicorn api.main:app --host 0.0.0.0 --port 8000"]
