# FastAPI Application — Analysis

**Task:** fastapi-app-analysis
**Phase:** analysis
**Date:** 2026-02-18

---

## 1. Codebase State

This is a **greenfield project**. The repository contains only artifact prompt files; no application source code exists yet. There are no existing patterns, utilities, or conventions to reuse from the current branch. The only prior commit (`92470a8`) references a rate-limiting task in a separate artifact, with no associated source files tracked.

**Implication:** All files listed in the constraint scope must be created from scratch. Every design decision falls to the implementing agent.

---

## 2. Affected Files

All files below must be **created** (none exist yet).

### Core Application
| File | Purpose |
|------|---------|
| `app/__init__.py` | Package marker |
| `app/main.py` | FastAPI app factory, router registration, middleware wiring |
| `app/config.py` | Pydantic `BaseSettings` config (env vars, JWT secrets, DB URL) |
| `app/models.py` | SQLAlchemy ORM models: `User`, `RefreshToken` (token blacklist) |
| `app/schemas.py` | Pydantic v2 request/response schemas for auth endpoints and error responses |
| `app/exceptions.py` | Custom exception classes: `AuthError`, `ValidationError`, `NotFoundError`, `ServiceUnavailableError` |
| `app/logging_config.py` | Structured JSON logging setup (`python-json-logger` or stdlib `logging.Formatter`) |
| `app/circuit_breaker.py` | Circuit breaker state machine (CLOSED → OPEN → HALF_OPEN) |

### Auth Module
| File | Purpose |
|------|---------|
| `app/auth/__init__.py` | Package marker |
| `app/auth/router.py` | FastAPI `APIRouter` with `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout` |
| `app/auth/service.py` | Business logic: user creation, credential verification, token management |
| `app/auth/jwt.py` | JWT encode/decode helpers using `python-jose`, access + refresh token generation |

### Middleware
| File | Purpose |
|------|---------|
| `app/middleware/__init__.py` | Package marker |
| `app/middleware/correlation.py` | Injects `X-Correlation-ID` header; stores in `contextvars.ContextVar` |
| `app/middleware/logging.py` | Logs every request/response (method, path, status, duration, correlation_id, user_id) |
| `app/middleware/error_handler.py` | Catches all unhandled exceptions; maps to consistent JSON error format; logs stack traces |

### Tests
| File | Purpose |
|------|---------|
| `tests/__init__.py` | Package marker |
| `tests/conftest.py` | pytest fixtures: in-memory SQLite DB, TestClient, test user factory |
| `tests/test_auth.py` | Tests for all four auth endpoints (happy paths + error paths) |
| `tests/test_circuit_breaker.py` | Unit tests for state transitions and fallback behavior |
| `tests/test_middleware.py` | Tests for correlation ID propagation and error handler response shape |

### Project Files
| File | Purpose |
|------|---------|
| `requirements.txt` | Pinned dependencies |
| `README.md` | Setup and usage documentation |

---

## 3. Dependencies

### External Libraries

| Package | Version Constraint | Usage |
|---------|-------------------|-------|
| `fastapi` | `>=0.111` | Web framework, OpenAPI generation |
| `uvicorn[standard]` | `>=0.29` | ASGI server |
| `sqlalchemy` | `>=2.0` | ORM, async-ready with sync fallback |
| `pydantic[email]` | `>=2.0,<3` | Data validation; `EmailStr` for registration |
| `pydantic-settings` | `>=2.0` | `BaseSettings` for config |
| `python-jose[cryptography]` | `>=3.3` | JWT signing/verification (HS256 or RS256) |
| `passlib[bcrypt]` | `>=1.7` | Password hashing |
| `python-multipart` | `>=0.0.9` | Required by FastAPI for form data |
| `pytest` | `>=8.0` | Test runner |
| `httpx` | `>=0.27` | `TestClient` dependency for FastAPI tests |
| `pytest-asyncio` | `>=0.23` | Async test support |

**Optional but recommended:**
- `python-json-logger` — simplifies structured JSON log output (alternative: custom `logging.Formatter`)
- `alembic` — database migrations (PostgreSQL readiness)

### Internal Module Dependencies (Dependency Graph)

```
app/main.py
  └── app/config.py
  └── app/logging_config.py
  └── app/middleware/correlation.py
  └── app/middleware/logging.py
  └── app/middleware/error_handler.py
  └── app/auth/router.py
        └── app/auth/service.py
              └── app/models.py
              └── app/auth/jwt.py
                    └── app/config.py
        └── app/schemas.py
        └── app/exceptions.py

app/circuit_breaker.py  (standalone, used by services calling external APIs)
```

**Middleware registration order matters** (see Risks §4.3).

---

## 4. Design Decisions & Patterns

### 4.1 Authentication

- **Token storage:** Refresh tokens stored in DB (`RefreshToken` table with `jti`, `user_id`, `expires_at`, `revoked`). Access tokens are stateless (short-lived, 15 min). Logout marks the refresh token as `revoked=True`.
- **Password hashing:** `passlib.context.CryptContext(schemes=["bcrypt"])`. Never store plaintext passwords.
- **JWT claims:** `sub` (user_id as string), `jti` (unique token ID for revocation), `exp`, `iat`, `type` (`access` or `refresh`).
- **Refresh token rotation:** On `/auth/refresh`, issue a new refresh token and revoke the old one to prevent replay attacks.

### 4.2 Structured Logging

- Use Python's stdlib `logging` with a custom JSON formatter (or `python-json-logger`).
- Log fields: `timestamp` (ISO 8601), `level`, `request_id` (= correlation ID), `endpoint`, `method`, `status_code`, `duration_ms`, `user_id` (nullable).
- Correlation ID stored in a `contextvars.ContextVar` so it's accessible anywhere in the request lifecycle without passing it explicitly.

### 4.3 Error Handling

Consistent error response schema:
```json
{
  "error": {
    "code": "AUTH_INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": {}
  },
  "request_id": "uuid-..."
}
```

- Custom exceptions carry an HTTP status code, error code string, and optional detail dict.
- The global handler in `error_handler.py` catches `HTTPException`, custom app exceptions, `RequestValidationError`, and bare `Exception` (fallback 500).
- Stack traces are logged at `ERROR` level but **never** included in the HTTP response body.

### 4.4 Circuit Breaker

State machine:
```
CLOSED  →(failure_count >= threshold)→  OPEN
OPEN    →(timeout elapsed)→             HALF_OPEN
HALF_OPEN →(success)→                   CLOSED
HALF_OPEN →(failure)→                   OPEN
```

- Implemented as a class with `__call__` or a `@circuit_breaker` decorator.
- State is in-process (per-worker); for multi-worker deployments, Redis-backed state would be needed (out of scope, flagged as open question).
- When OPEN: raise `ServiceUnavailableError` or return a configured fallback value.

---

## 5. Risks & Edge Cases

### 5.1 Security Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| JWT secret exposed in logs or error messages | HIGH | Never log `config.secret_key`; use `SecretStr` in Pydantic config |
| Refresh token replay (stolen token reuse) | HIGH | Refresh token rotation + DB revocation check on every `/auth/refresh` |
| Timing side-channel on password comparison | MEDIUM | `passlib` constant-time comparison handles this |
| JWT `alg: none` attack | HIGH | Explicitly specify algorithm in `jose.jwt.decode(algorithms=["HS256"])` |
| Brute-force login | MEDIUM | Rate limiting (not in scope here; separate task-001 addresses this) |
| SQL injection via ORM | LOW | SQLAlchemy parameterized queries; never use raw SQL with user input |
| Stack traces in error responses | HIGH | Global handler must catch `Exception` and strip tracebacks before responding |

### 5.2 Functional Risks

| Risk | Description |
|------|-------------|
| Token blacklist growth | `RefreshToken` table grows unboundedly; need a cleanup job for expired tokens |
| Circuit breaker state not shared across workers | In-process state means each uvicorn worker has its own circuit breaker; a failing service could still receive traffic from workers whose breaker hasn't opened yet |
| Pydantic v2 breaking changes | Pydantic v2 has different validators/validators syntax from v1; must use `model_validator`, `field_validator`, and `model_config` (not `class Config`) |
| SQLAlchemy 2.0 session management | Must use `Session` as context manager or dependency injection; avoid leaking sessions |
| `asyncio` vs sync | FastAPI supports async endpoints; SQLAlchemy 2.0 sync sessions work fine in sync endpoints, but mixing async/sync carelessly causes issues |

### 5.3 Middleware Order Risk

FastAPI/Starlette middleware is applied in **reverse registration order**. The intended order of execution for incoming requests should be:

1. Correlation ID injection (outermost — must run first so all subsequent logs have a `request_id`)
2. Logging middleware
3. Error handler middleware (innermost — catches exceptions from route handlers)

Registration in `main.py` must therefore add them in **reverse** of this order (error_handler first, then logging, then correlation).

### 5.4 OpenAPI / Swagger

- FastAPI generates OpenAPI 3.x automatically; `/docs` and `/redoc` are enabled by default.
- To document JWT Bearer auth in the spec: use `HTTPBearer` security scheme or `OAuth2PasswordBearer`. Must be declared at the app level and referenced per-router.
- Request/response models must be proper Pydantic models (not dicts) for OpenAPI schema generation to work correctly.

---

## 6. Open Questions

1. **Token storage strategy:** Should refresh tokens be stored in the DB (current plan) or in an HTTP-only cookie? Cookie approach is more XSS-resistant but complicates cross-origin setups.

2. **Multi-worker circuit breaker:** Should the circuit breaker use Redis for shared state across multiple uvicorn workers? The in-process implementation is simpler but less effective in production multi-worker deployments.

3. **Async vs sync DB:** Should SQLAlchemy be used in async mode (`asyncpg` + `create_async_engine`) or sync mode? Async adds complexity but improves throughput under I/O load. The spec doesn't specify.

4. **Refresh token lifetime:** Not specified in requirements. Common values: 7 days (mobile) or 1 day (web). Needs a config value.

5. **User model scope:** The spec only mentions `email` and `password`. Should `User` include `id`, `created_at`, `is_active`, `is_verified`? A minimal implementation needs at least `id`, `email`, `hashed_password`.

6. **`/auth/logout` token scope:** Does logout invalidate only the provided refresh token, or all refresh tokens for the user (all sessions)? "Invalidate tokens" is ambiguous.

7. **Circuit breaker fallback:** The spec says "fallback responses when circuit is open" — should this be a generic `503 Service Unavailable` or a cached last-known-good response? The latter requires additional state.

8. **`python-json-logger` dependency:** The spec doesn't list it explicitly. If not desired, a custom `logging.Formatter` subclass achieves the same result without an extra dependency.

---

## 7. Implementation Recommendations for Downstream Agents

1. **Start with `app/config.py`** — everything depends on it (DB URL, JWT secret, token expiry settings).
2. **`app/models.py` before `app/auth/service.py`** — service layer depends on ORM models.
3. **`app/exceptions.py` before middleware** — error handler imports custom exceptions.
4. **`app/logging_config.py` before middleware** — logging middleware uses the configured logger.
5. **Wire middleware in `app/main.py` last**, after all modules are implemented.
6. **`tests/conftest.py`** should use an in-memory SQLite engine and override the `get_db` dependency.
7. Use `pytest-asyncio` with `asyncio_mode = "auto"` in `pytest.ini` or `pyproject.toml` if async endpoints are used.

---

## 8. Summary

This is a complete greenfield implementation. All 22 files in scope must be created. The four cross-cutting concerns (auth, logging, error handling, circuit breaker) are relatively independent and can be developed in parallel, but the middleware wiring in `main.py` is a final integration point that depends on all other modules being complete. The highest-risk areas are JWT security (algorithm pinning, token revocation), middleware registration order, and Pydantic v2 syntax compliance.
