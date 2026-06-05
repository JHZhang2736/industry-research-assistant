# syntax=docker/dockerfile:1.7

# === builder stage ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build essentials for any wheels needing compilation (psycopg2-binary 实际不需要但有些 wheels 需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a --user prefix for cleaner copy in next stage
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# === runtime stage ===
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/root/.local/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY app/ /app/

EXPOSE 8000

# Run uvicorn directly (matches app_main.py's __main__ block)
CMD ["python", "app_main.py"]
