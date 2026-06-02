# Security Protocols

This document details the security implementations integrated into the project.

## 1. Authentication & Token Revocation

The application implements JWT authentication using **HS256** signatures. However, pure JWTs are stateless and cannot be easily revoked before expiration. To address this, we use a hybrid **JWT + Redis Session** model:

```
[Request with JWT]
       │
       ▼
1. Decode JWT Signature (HS256)
       │
       ├─► Invalid Signature/Expired ──► [HTTP 401 Unauthorized]
       ▼
2. Check Redis cache for key "session:{user_id}:{jti}"
       │
       ├─► Key NOT present (revoked) ──► [HTTP 401 Unauthorized]
       ▼
3. Query Postgres for User ID
       │
       ├─► User not found/inactive   ──► [HTTP 401 Unauthorized]
       ▼
[Access Granted]
```

*   **Logout Invalidation:** When a user logs out, the server deletes `session:{user_id}:{jti}` from Redis. Any subsequent requests using that JWT will immediately fail.

## 2. Multi-Role Authorization

The role checker middleware provides declarative endpoint protection:
```python
@router.post("/some-route", dependencies=[Depends(RoleChecker(allowed_roles=["ADMIN", "CONTROL"]))])
```
*   **Role Mapping:** Roles are stored in a database JSON column on the user record.
*   **Admin Override:** Users with the `ADMIN` role are granted access to all protected endpoints by default, bypassing check constraints.

## 3. Scoped API Keys for Integrations

Third-party clients can call endpoints using API keys passed via the `X-API-Key` header:
*   **Storage:** Keys are hashed using **SHA-256** before database insertion. We never store raw API keys.
*   **Identification:** Keys contain a public prefix (e.g. `ak_12345`) to allow users to identify keys without exposing the raw secret.
*   **Scopes:** Keys carry a list of granted scopes (e.g. `assets:audit`). The dependency class `ScopedAPIKeyChecker(required_scopes=[...])` matches the key hash, verifies its active state, evaluates its expiry, and confirms the client holds all required scopes.

## 4. Log Masking of Sensitive Data

To prevent accidental leaks of PII or credentials into system logs (stdout, log files, or container aggregators), a custom logging formatter intercepts and sanitizes records:
*   **Scan List:** `settings.SENSITIVE_KEYS` lists terms to mask (e.g. `password`, `token`, `secret`, `authorization`, `credit_card`).
*   **JSON Masking:** If a log message or query payload contains JSON, it is parsed and keys matching the scan list are replaced recursively with `***FILTERED***`.
*   **String/Form Masking:** Fallback regex patterns match query parameters (`key=value`) and form structures to sanitize them.
*   **Scope:** Applied globally to both FastAPI HTTP logs and Celery background worker task execution logs.

## 5. Network Controls (IP Whitelisting)

Selected endpoints are whitelisting-restricted:
*   **IP Resolution:** Resolves client IPs from `X-Forwarded-For` (first IP) when running behind load balancers/proxies, falling back to `request.client.host`.
*   **Validation:** Evaluates the IP against a subnet/address whitelist configured in `settings.ALLOWED_IPS`.
