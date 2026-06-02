# Docker Containerization & Security Guide

This document details the production-grade containerization architecture, security hardening, and orchestration configurations implemented in this project.

---

## 1. Hardened Production Dockerfile

The application's `Dockerfile` uses a **multi-stage build** designed for security, minimal image size, and performance.

### Multi-Stage Architecture
*   **Stage 1 (Builder):** Uses `python:3.13-slim`. Installs `uv` and compiling libraries (`build-essential`) to install all project dependencies into a virtual environment (`/app/.venv`).
*   **Stage 2 (Runtime):** Copies only the compiled virtual environment and source code. None of the build compilers (like gcc or make) are carried over, minimizing the runtime attack surface.

### Security Hardening Measures
1.  **Least Privilege User (Non-Root):**
    The container process does not run as `root`. We create a dedicated system user/group with explicit IDs:
    ```dockerfile
    RUN groupadd -r -g 10001 appgroup && \
        useradd -r -M -d /app -s /sbin/nologin -g appgroup -u 10001 appuser
    USER 10001:10001
    ```
    This prevents potential container breakouts from gaining root privileges on the host system.
2.  **Anti-Mutation File Permissions:**
    All code and packages copied into the runtime stage are owned by `root:root`:
    ```dockerfile
    COPY --from=builder --chown=root:root /app/.venv /app/.venv
    COPY --chown=root:root . .
    ```
    Because the container runs as `appuser` (UID `10001`), the application has no write access to its own files. If an attacker exploits a remote code execution (RCE) vulnerability, they cannot modify or append malicious code to existing Python files.
3.  **Active Security Patching:**
    Both build stages execute `apt-get update && apt-get upgrade -y` to pull in the latest Debian system security patches.
4.  **Alpine/Debian Slim Footprint:**
    Temporary apt indexes (`/var/lib/apt/lists/*`) are pruned in the same layer they are created to reduce size and remove cached diagnostic tools.

---

## 2. Container Healthchecks

Container healthchecks are declared for all key services in the stack to support self-healing and zero-downtime rolling updates.

### FastAPI Application Healthcheck
Configured directly in the `Dockerfile`:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```
*   **`--interval=30s`**: Runs check every 30 seconds.
*   **`--timeout=5s`**: Wait up to 5 seconds. If blocked, counts as a failure.
*   **`--start-period=5s`**: Grace period during application boot (ignores initial failures).
*   **`--retries=3`**: 3 consecutive failures transitions the container to `unhealthy`.
*   **`curl -f`**: Returns a non-zero exit code on HTTP errors (like 500 Server Errors).

### Auxiliary Service Healthchecks (Compose)
Declared in `compose.yml` to block dependent containers until prerequisites are fully initialized:
*   **PostgreSQL (`db`):** Uses `pg_isready -U postgres -d app` to wait until Postgres is ready to accept connections.
*   **Redis (`redis`):** Uses `redis-cli ping` to verify cache availability.
*   **RabbitMQ (`rabbitmq`):** Uses `rabbitmq-diagnostics -q ping` to verify queue broker availability.
*   **LocalStack (`localstack`):** Uses `curl` against the localstack status endpoint to verify S3 mock availability.

---

## 3. Local Development Features in Compose

To support live development inside containers:
1.  **Code Volume Mounting (`.:/app`):** The local workspace is mounted into the container. Uvicorn monitors this mount, enabling hot-reloading (`--reload`) instantly when you save changes in your local IDE.
2.  **Environment Isolation via `.env`:** We use `env_file: - .env` across services in `compose.yml`. This keeps secrets out of Compose configuration files and maps environment contexts dynamically.
