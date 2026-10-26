# syntax=docker/dockerfile:1
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS wheels
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip wheel --no-cache-dir --require-hashes --wheel-dir /wheels -r requirements.lock

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OEIS_DISABLE_ENV_FILE=true
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends unixodbc tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system oeis && useradd --system --gid oeis --home-dir /app oeis \
    && mkdir /data && chown oeis:oeis /data
COPY --from=wheels /wheels /wheels
COPY backend/requirements.txt backend/requirements.lock ./
RUN pip install --no-cache-dir --no-index --find-links=/wheels --require-hashes -r requirements.lock \
    && rm -rf /wheels
COPY --chown=oeis:oeis backend/ ./
COPY --from=web --chown=oeis:oeis /web/dist /frontend/dist
COPY --chmod=755 docker/entrypoint.sh /entrypoint.sh
USER oeis
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python","-c","import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read()"]
ENTRYPOINT ["/entrypoint.sh"]
