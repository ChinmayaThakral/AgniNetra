# AgniNetra Live: the app and its evening feed in one container, apps/live/serve.py.
# Mount a persistent volume at /app/data so past evenings survive a redeploy.

FROM node:22-slim AS web
WORKDIR /web
COPY apps/live/web/package.json apps/live/web/package-lock.json ./
RUN npm ci
COPY apps/live/web/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock.txt ./
RUN pip install -c requirements.lock.txt duckdb h5py matplotlib numpy pillow python-dotenv requests
RUN python -c "import duckdb; duckdb.connect().execute('INSTALL spatial')"
COPY pyproject.toml ./
COPY ml ml
COPY apps/live apps/live
COPY --from=web /web/dist apps/live/web/dist
EXPOSE 3000
CMD ["python", "-m", "apps.live.serve"]
