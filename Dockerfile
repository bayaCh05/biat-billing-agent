FROM python:3.11-slim

# System dependencies
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
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 biatit

WORKDIR /app

# Install Python dependencies first (layer cache — only invalidated when
# pyproject.toml changes, not when application code changes)
COPY pyproject.toml ./
RUN python3 -c "import tomllib,subprocess,sys; d=tomllib.load(open('pyproject.toml','rb')); deps=d['project']['dependencies']+d['project']['optional-dependencies']['dev']; subprocess.run([sys.executable,'-m','pip','install','--no-cache-dir']+deps,check=True)"

# Copy source code
COPY . .

# Install the package itself (no-deps: already installed above)
RUN pip install --no-cache-dir --no-deps -e .

# Create data directories and set ownership
RUN mkdir -p data exports invoices uploads inbox logs \
    && chown -R biatit:biatit /app

USER biatit

ENV STREAMLIT_SERVER_PORT=8501
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s \
    --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["sh", "-c", \
    "python -c \"\
from src.storage.db import build_engine, init_db; \
import os; \
db_url = os.environ.get('DATABASE_URL', 'sqlite:////app/data/biat_billing.db'); \
engine = build_engine(db_url); \
init_db(engine); \
print('Database initialised.')\" \
&& streamlit run app/Home.py \
   --server.port=8501 \
   --server.address=0.0.0.0"]
