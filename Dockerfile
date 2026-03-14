# ── Stage 1a: Build frontend ───────────────────────────
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# ── Stage 1b: Build docs ──────────────────────────────
FROM node:22-alpine AS docs

WORKDIR /build
COPY docs-site/package.json docs-site/package-lock.json* ./
RUN npm ci
COPY docs-site/ .
RUN npm run build

# ── Stage 2: Build Python ─────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .python-version README.md ./
COPY src/ src/
COPY plugin/skills/ plugin/skills/
COPY templates/ templates/
COPY static/ static/

# Copy built frontend into static/app/ (Vite outputs to ../static/app relative to /build)
COPY --from=frontend /static/app/ /app/static/app/

# Build wheel
RUN uv build --wheel --out-dir /dist

# ── Stage 3: Production ───────────────────────────────
FROM python:3.12-slim

# Security: non-root user
RUN groupadd -r canon -g 1001 && \
    useradd -r -g canon -u 1001 -d /app canon

WORKDIR /app

# Install the wheel
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir "$(ls /tmp/*.whl)[cloud]" && rm -rf /tmp/*.whl

# Copy templates and static files (including built SPA)
COPY --from=build /app/templates/ /app/templates/
COPY --from=build /app/static/ /app/static/

# Copy built docs site
COPY --from=docs /build/.vitepress/dist/ /app/docs-site/.vitepress/dist/

# Switch to non-root user
USER 1001

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:3000/healthz')" || exit 1

EXPOSE 3000

ENTRYPOINT ["uvicorn", "canon.main:app", "--host", "0.0.0.0", "--port", "3000", "--proxy-headers", "--forwarded-allow-ips", "*"]
