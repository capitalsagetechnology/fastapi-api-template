# Stage 1: Build virtualenv and install dependencies
FROM python:3.13-slim AS builder

# Configure build environment
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/venv

# Install build dependencies and apply security updates
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy uv binary from official registry
COPY --from=ghcr.io/astral-sh/uv:0.11.4 /uv /uvx /bin/

WORKDIR /app

# Copy dependency configs
COPY pyproject.toml uv.lock ./

# Install dependencies (without installing the project itself)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev


# Stage 2: Final runtime container
FROM python:3.13-slim

# Configure runtime environment
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Apply system updates and install curl for healthchecks
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create a non-privileged system user/group with explicit IDs and no shell access
RUN groupadd -r -g 10001 appgroup && \
    useradd -r -M -d /app -s /sbin/nologin -g appgroup -u 10001 appuser

WORKDIR /app

# Copy virtualenv from builder with secure permissions (owned by root, read-only by appuser)
COPY --from=builder --chown=root:root /venv /venv

# Copy application source code (owned by root, read-only by appuser to prevent runtime mutation)
COPY --chown=root:root . .

# Set container user to non-root appuser
USER 10001:10001

EXPOSE 8000

# Container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command runs Uvicorn server
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
