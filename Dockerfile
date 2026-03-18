# ── Stage 1: Build Python ─────────────────────────────
FROM python:3.12-slim AS build

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml .python-version README.md ./
COPY src/ src/
COPY plugin/skills/ plugin/skills/

# Build wheel
RUN uv build --wheel --out-dir /dist

# ── Stage 2: Production ──────────────────────────────
FROM python:3.12-slim

# Security: non-root user
RUN groupadd -r canon -g 1001 && \
    useradd -r -g canon -u 1001 -d /app canon

WORKDIR /app

# Install the wheel
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

# Switch to non-root user
USER 1001

ENTRYPOINT ["canon"]
