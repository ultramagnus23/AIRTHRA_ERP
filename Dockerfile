# FastAPI backend image, for Render (or any Docker host). Nothing in this
# repo was ever containerized itself before this - api/main.py and the
# workers only ever ran as local Python processes against docker-compose's
# infra containers (Postgres/MinIO/Mosquitto/Grafana/Caddy). This is the
# first Dockerfile in the project, needed because a hosting platform can't
# run "python api/main.py in a terminal" the way local dev has all session.
FROM python:3.13-slim

WORKDIR /app

# System deps for psycopg[binary]/asyncpg's C extensions and reportlab's
# font handling - kept minimal, matching the "no dead weight" discipline
# the rest of this codebase follows.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# API_PORT defaults to 8000 (api/config.py); Render injects its own $PORT
# and expects the service to bind to it, so the start command below reads
# $PORT with a fallback rather than hardcoding 8000.
EXPOSE 8000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
