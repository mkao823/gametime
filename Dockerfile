# MLB pregame predictions API (FastAPI + LightGBM ensemble).
# Data and trained models are NOT baked in — mount a persistent volume at /data.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs

RUN pip install --no-cache-dir -e '.[api,mlb]'

ENV GAMETIME_ROOT=/data \
    GAMETIME_CONFIG=configs/mlb.yaml

EXPOSE 8000

# Fly.io and docker-compose health checks: GET /health
CMD ["uvicorn", "gametime.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
