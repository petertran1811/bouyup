# BuoyUp v4 · one image = API (FastAPI) + web UI (static files served at /app).
FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv
COPY BackEnd/src/requirements.txt BackEnd/src/requirements.txt
COPY BackEnd/src/Reid/requirements.txt BackEnd/src/Reid/requirements.txt
# insightface (face authentication) compiles a small C extension; the compiler is removed afterwards.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install -r BackEnd/src/requirements.txt \
    && apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY BackEnd/src BackEnd/src
COPY BackEnd/API_config/.env.example BackEnd/API_config/.env.example
COPY Frontend Frontend

# Runtime state (SQLite database, autopilot lock) lives in /data, a volume.
RUN useradd --system --uid 10001 --home /data buoyup \
    && mkdir -p /data && chown buoyup:buoyup /data
USER buoyup
WORKDIR /data

ENV FRONTEND_DIR=/srv/Frontend \
    DATABASE_URL=sqlite:////data/buoyup.db \
    ENV_FILE=/data/.env-not-used \
    FACE_MODEL_ROOT=/data/insightface \
    FACE_DATA_DIR=/data/faces \
    PORT=8000

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/healthz',timeout=4)"

# One worker: the autopilot (Agents 4/5) runs in-process and SQLite has one writer.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir /srv/BackEnd/src --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
