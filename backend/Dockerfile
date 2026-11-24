FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/backend \
    PREDRIVE_ENABLE_LEGACY_AI=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 predrive

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY supabase /app/supabase
COPY scripts /app/scripts

RUN mkdir -p /app/data && chown -R predrive:predrive /app

USER predrive

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
