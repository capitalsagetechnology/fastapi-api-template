# System Architecture Design

This document details the architectural components and data flows of the template application.

## Directory Structure & Component Responsibility

The project follows a standard service-oriented architecture, keeping concerns cleanly separated:

```
fastapi-template/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── src/
│   ├── main.py
│   ├── core/
│   │   ├── config.py       # Pydantic Settings
│   │   ├── database.py     # SQLModel engine and session
│   │   ├── security.py     # Password hashing, JWT utils
│   │   ├── logging.py      # Colored logs, masking formatter
│   │   └── middleware.py   # Request/Response logging middleware
│   ├── models/
│   │   ├── base.py         # Timestamped models
│   │   ├── user.py         # User, Invitation models
│   │   └── api_key.py      # Scoped API Key model
│   ├── services/
│   │   ├── s3.py           # S3 client wrapper
│   │   ├── email.py        # SendGrid + Jinja email templates
│   │   └── auth.py         # Registration, invitation and login services
│   ├── api/
│   │   ├── deps.py         # FastAPI dependencies (auth, db, keys, whitelist)
│   │   └── v1/
│   │       ├── auth.py     # Login, invite, register routes
│   │       ├── users.py    # Profile management and api key creation
│   │       └── assets.py   # S3 uploads, IP Whitelist & Scoped Keys demo
│   ├── worker/
│   │   ├── celery_app.py   # Celery configurations and logging signals
│   │   └── tasks.py        # Async task handlers (e.g. emails)
│   └── templates/
│       └── email/
│           ├── base.html   # Base HTML responsive layout
│           ├── invite.html # Invite template
│           └── welcome.html# Welcome template
├── alembic/
│   ├── env.py              # Alembic environment config (uses SQLModel metadata)
│   └── script.py.mako
├── alembic.ini
└── tests/
    ├── conftest.py         # Pytest client, SQLite & services mocks
    └── test_api.py         # E2E integration test suite
```

---

## Service Interactions & Boundaries

### 1. Database Layer (PostgreSQL & SQLModel)
All database interactions occur asynchronously. FastAPI routers acquire database sessions via the `get_db` dependency which yields an `AsyncSession` from the `async_sessionmaker`. The schemas are defined using `SQLModel` which translates directly to both Pydantic models (for API data parsing and validation) and SQLAlchemy Table metadata (for ORM mapping).

### 2. Session Management Layer (Redis & JWT)
Authentications use stateless JWTs combined with a stateful session record in Redis:
*   On login, the `AuthService` issues a JWT with a unique ID (`jti`) and writes `session:{user_id}:{jti}` to Redis.
*   On every API request, the `get_current_user` dependency queries Redis to ensure the session token is active.
*   On logout, the Redis key is deleted. This immediately revokes the JWT before its official expiry.

### 3. Background Task Queue (RabbitMQ & Celery)
Long-running and external I/O operations (such as sending HTML emails) are deferred to Celery:
*   The API dispatches a task to the queue using `task.delay()`.
*   RabbitMQ acts as the message broker, storing and routing task payloads.
*   The Celery Worker processes the tasks in a separate container, communicating directly with Postgres for state updates and SendGrid for email delivery.

### 4. Centralized Storage Abstraction (S3)
Asset handling is abstracted under `S3Service`.
*   Development: Mounts LocalStack in docker-compose. Files uploaded locally write to a mocked bucket and return a localhost-mapped URL.
*   Production: Connects directly to AWS S3.
*   The application code is entirely agnostic to the environment; it receives an S3 URL upon successful upload.
