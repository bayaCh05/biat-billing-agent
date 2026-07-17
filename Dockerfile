# ── Stage 1: build React SPA ─────────────────────────────────────────────────
# node:20-slim (glibc/Debian), not node:20-alpine (musl): Vite 8's Rolldown
# bundler ships platform-native binaries (@rolldown/binding-*) that don't
# resolve reliably on musl (npm/cli#4828) — this stage is discarded after
# dist/ is copied out below, so its image size doesn't affect the final image.
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
# node 20's bundled npm (10.8.2) has a libc-detection bug that silently skips
# installing platform-native optional deps (rolldown's own bundler binding,
# lightningcss, ...) inside this image — verified to affect npm ci itself,
# not just a stale lockfile. npm 11 does not have this bug; upgrading it
# before install is the fix, not switching package managers or images.
RUN npm install -g npm@11 && npm ci

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
# torch (pulled in transitively by sentence-transformers — not a direct dep)
# resolves to PyPI's default manylinux wheel, which bundles a full CUDA
# runtime (torch itself ~430MB, plus nvidia_cudnn/nvidia_cublas/... on top —
# multi-GB total) even though this container has no GPU. That's what was
# blowing past pip's read timeout repeatedly, not network flakiness — the
# fix is installing the CPU-only build from PyTorch's own index first, so
# the resolver below never touches the CUDA wheel.
RUN pip install --no-cache-dir --timeout 120 --retries 5 \
    --index-url https://download.pytorch.org/whl/cpu torch
# --timeout/--retries: some deps here are still large enough that pip's
# default 15s read timeout can trip mid-download on an ordinary connection.
RUN python3 -c "import tomllib,subprocess,sys; d=tomllib.load(open('pyproject.toml','rb')); deps=d['project']['dependencies']+d['project']['optional-dependencies']['dev']; subprocess.run([sys.executable,'-m','pip','install','--no-cache-dir','--timeout','120','--retries','5']+deps,check=True)"

COPY . .
# No `pip install -e .` here: the app runs via PYTHONPATH=/app/backend +
# uvicorn (see ENTRYPOINT below), never via an installed `invoice-agent`
# package or the `review-queue` console-script entry point — and pyproject.toml
# has no explicit [tool.setuptools.packages.find], so an editable install of
# the repo root fails on setuptools' flat-layout ambiguity (data/, exports/,
# logs/, config/, docker/, backend/, frontend/ all look like top-level
# packages to it). Dependencies themselves were already installed above.

# Inject the compiled SPA from stage 1
COPY --from=frontend-build /frontend/dist /app/frontend/dist

RUN mkdir -p data exports invoices uploads inbox logs \
    && chown -R biatit:biatit /app

USER biatit

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=/app/backend

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
