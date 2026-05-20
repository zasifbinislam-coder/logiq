FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src \
    LOGIQ_BASE_DIR=/app \
    LOGIQ_DB_PATH=/app/data/logiq.db \
    LOGIQ_COOKIE_SECURE=1 \
    HOST=0.0.0.0 \
    PORT=8765

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/
COPY web/ ./web/

# /app/data and /app/reports should be mounted as a persistent volume by
# the host platform — without it, the SQLite DB and any uploaded logs
# disappear on every container restart.
RUN mkdir -p /app/data/uploads /app/reports

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:${PORT}/api/stats > /dev/null || exit 1

CMD ["python", "-m", "logiq.api"]
