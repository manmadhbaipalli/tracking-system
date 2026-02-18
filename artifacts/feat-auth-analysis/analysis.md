# Analysis: JWT-Based User Authentication

**Task:** feat-auth-analysis
**Pipeline:** feat-auth | **Phase:** analysis
**Date:** 2026-02-18

---

## 1. Codebase State

The repository is a **greenfield project**. No application source files exist yet. The only committed content is:

- `artifacts/task-001/prompt.txt` — a sibling agent task for rate-limiting `/api/users`
- `artifacts/task-001/agent.log` — log from that agent (shows an error; no implementation was written)

The sibling task (`task-001`) targets `src/api/users.py` and `tests/test_users.py`, which implies the project will be structured as a Flask or FastAPI application under `src/`. Since no framework files exist yet, framework choice must be established in this phase.

---

## 2. Affected Files

### Files within scope (locked to this agent)

| File | Status | Purpose |
|---|---|---|
| `src/auth.py` | Must be created | Core authentication logic: JWT creation, validation, user login/logout/refresh |
| `src/middleware.py` | Must be created | Authentication middleware: request interception, token verification, request decoration |
| `tests/test_auth.py` | Must be created | Unit and integration tests for all auth functionality |

### Files outside scope (other agents or shared infrastructure)

These files will need to exist for `src/auth.py` and `src/middleware.py` to work, but this agent must NOT create or modify them:

| File | Owner | Dependency reason |
|---|---|---|
| `src/app.py` or `src/main.py` | Shared/other agent | Application factory; registers auth blueprints/routers |
| `src/models.py` or `src/db/models.py` | Shared/other agent | User model with `id`, `username`/`email`, `password_hash` fields |
| `src/config.py` | Shared/other agent | `SECRET_KEY`, `JWT_ALGORITHM`, token TTL settings |
| `src/api/users.py` | task-001 agent | Rate-limited user endpoint; may require auth middleware |
| `tests/conftest.py` | Shared/other agent | Shared fixtures (app client, DB session, test users) |
| `requirements.txt` / `pyproject.toml` | Shared/other agent | Must declare `PyJWT`, `bcrypt`/`passlib`, `Flask`/`FastAPI` |

---

## 3. Existing Patterns

No existing patterns are present in the codebase. The implementation agent should establish conventions that future agents and developers can follow. Recommended patterns based on the sibling task structure:

- **Module layout:** `src/<domain>.py` flat layout (inferred from `src/auth.py`, `src/middleware.py`, `src/api/users.py`)
- **Test layout:** `tests/test_<module>.py` per-module test files
- **Framework:** Flask is the most probable choice given the flat module structure and the simplicity implied by task-001's token-bucket rate limiter description. FastAPI is also reasonable.

---

## 4. Dependencies

### External Libraries Required

| Library | Purpose | Notes |
|---|---|---|
| `PyJWT` (>=2.0) | JWT creation and validation | Prefer over `python-jose`; actively maintained |
| `bcrypt` or `passlib[bcrypt]` | Password hashing | `passlib` provides a higher-level API |
| `Flask` or `FastAPI` | Web framework | Must match whatever `src/api/users.py` uses |
| `pytest` | Test runner | Standard; already implied by test file naming convention |
| `pytest-flask` or `httpx` | Test HTTP client | `pytest-flask` for Flask; `httpx` for FastAPI async tests |

### Internal Module Dependencies

```
src/auth.py
  ├── depends on: src/models.py (User model lookup)
  ├── depends on: src/config.py (SECRET_KEY, algorithm, token TTL)
  └── produces: JWT access token, refresh token

src/middleware.py
  ├── depends on: src/auth.py (token validation function)
  └── decorates: route handlers in src/api/*.py

tests/test_auth.py
  ├── depends on: src/auth.py (unit-testable functions)
  ├── depends on: src/middleware.py (integration path)
  └── depends on: tests/conftest.py (app fixture, test DB, test user)
```

---

## 5. Design Recommendations for Implementation Agent

### Endpoints to implement (in `src/auth.py`)

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/login` | Accept credentials, return `access_token` + `refresh_token` |
| `POST` | `/auth/logout` | Invalidate refresh token (server-side blocklist or stateless) |
| `POST` | `/auth/refresh` | Accept valid refresh token, return new `access_token` |

### JWT Token design

- **Access token:** Short-lived (e.g., 15 minutes). Contains `sub` (user ID), `exp`, `iat`, `type: "access"`.
- **Refresh token:** Long-lived (e.g., 7 days). Contains `sub`, `exp`, `iat`, `type: "refresh"`. Should be stored server-side (DB or Redis) to support revocation on logout.
- **Algorithm:** `HS256` is simplest for a single-service deployment; `RS256` is better for multi-service. `HS256` recommended for this scope.

### Middleware design (in `src/middleware.py`)

- Implement a `require_auth` decorator (Flask) or dependency (FastAPI) that:
  1. Extracts the `Authorization: Bearer <token>` header.
  2. Validates the JWT signature and expiry.
  3. Confirms `type == "access"`.
  4. Attaches the decoded user identity to the request context (`g.user_id` in Flask, `request.state.user_id` in FastAPI).
  5. Returns `401 Unauthorized` on any failure with a JSON body: `{"error": "unauthorized", "message": "<reason>"}`.

---

## 6. Risks and Edge Cases

### Security Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Weak `SECRET_KEY` | Critical | Enforce minimum length (≥32 bytes), loaded from environment variable, never hardcoded |
| Refresh token reuse after logout | High | Store refresh tokens server-side; delete on logout; check presence before issuing new access token |
| Token type confusion | High | Always validate the `type` claim; reject access tokens on `/auth/refresh` and refresh tokens on protected routes |
| Timing attacks on password comparison | Medium | Use `passlib`/`bcrypt` which are constant-time by design |
| Missing expiry enforcement | High | Always check `exp` claim; PyJWT does this by default but must not disable verification |
| Brute-force login | Medium | Rate limiting on `/auth/login` (consistent with the `task-001` rate-limiter pattern) |
| Verbose error messages | Low | Do not distinguish "user not found" from "wrong password" — return a generic `401` for both |

### Breaking Change Risks

| Risk | Notes |
|---|---|
| `src/api/users.py` may require auth | The `task-001` agent implements rate limiting for `/api/users`. If that endpoint should be protected, the middleware from `src/middleware.py` must be applied there. Coordination needed. |
| No shared `conftest.py` yet | Tests will fail if no test fixtures (app, client, DB) are defined. The implementation agent must either create `tests/conftest.py` (if not locked) or include fixtures directly in `tests/test_auth.py`. |
| Framework not yet chosen | If `src/auth.py` uses Flask but `src/api/users.py` (task-001) uses FastAPI, they will be incompatible. The implementation agent must confirm the framework before writing code. |

### Edge Cases

- Expired access token with valid refresh token: client should call `/auth/refresh`, not retry protected endpoint.
- Refresh token passed to a protected route (not `/auth/refresh`): must be rejected — validate `type` claim.
- Concurrent refresh requests with same refresh token (race condition): use DB-level atomic operations or token rotation (issue new refresh token, invalidate old one).
- User deleted/disabled after token issuance: middleware should optionally validate user still exists in DB (adds latency; trade-off).
- Clock skew between services: set a small `leeway` (e.g., 10s) in JWT verification to tolerate minor skew.

---

## 7. Open Questions

1. **Web framework:** Is the project Flask or FastAPI? The task does not specify. This is the most critical decision before implementation begins. The sibling agent's task (`task-001`) also did not produce any code, so the framework remains unestablished.

2. **User model:** Where is the `User` model defined, and what fields does it have? `src/auth.py` needs to look up users by username or email and verify their password hash.

3. **Database / ORM:** Is the project using SQLAlchemy, SQLite, PostgreSQL, or another data store? Refresh token storage strategy depends on this.

4. **Refresh token storage:** Should refresh tokens be stored in the database (full revocation support) or be stateless (no revocation, simpler)? Stateless logout would only clear the client-side token.

5. **Token transport:** Should access tokens be returned in the response body (standard for SPAs/mobile) or set as `HttpOnly` cookies (better for browser security)? This affects CSRF risk.

6. **Logout behavior:** Is "logout" purely client-side (discard token) or server-side (invalidate refresh token)? Server-side is safer but requires storage.

7. **Rate limiting on auth endpoints:** Should `/auth/login` be rate-limited (to prevent brute force)? The `task-001` pattern suggests rate limiting is in scope for this project.

8. **Test database:** Should `tests/test_auth.py` use an in-memory SQLite DB, mocks, or a test instance of the production DB? No `conftest.py` exists yet to establish this.

9. **`conftest.py` ownership:** Is `tests/conftest.py` within scope for this agent or locked to another agent? If locked out, `tests/test_auth.py` will need self-contained fixtures.

---

## 8. Recommended File Structure

```
src/
├── app.py              # Application factory (NOT this agent's scope)
├── config.py           # Configuration / secrets (NOT this agent's scope)
├── models.py           # User model (NOT this agent's scope)
├── auth.py             # ← THIS AGENT: login, logout, refresh logic + routes
├── middleware.py       # ← THIS AGENT: JWT validation decorator/dependency
└── api/
    └── users.py        # task-001 agent's file

tests/
├── conftest.py         # Shared fixtures (potentially NOT this agent's scope)
├── test_auth.py        # ← THIS AGENT: auth tests
└── test_users.py       # task-001 agent's file
```

---

## 9. Test Plan (for `tests/test_auth.py`)

The implementation agent should write tests covering:

### Login (`POST /auth/login`)
- [ ] Valid credentials return `200` with `access_token` and `refresh_token`
- [ ] Wrong password returns `401`
- [ ] Non-existent user returns `401` (same message as wrong password)
- [ ] Missing fields return `400`

### Refresh (`POST /auth/refresh`)
- [ ] Valid refresh token returns new `access_token`
- [ ] Expired refresh token returns `401`
- [ ] Access token passed to refresh endpoint returns `401`
- [ ] Invalid/tampered token returns `401`

### Logout (`POST /auth/logout`)
- [ ] Valid refresh token causes it to be invalidated
- [ ] Subsequent refresh with the same token returns `401`

### Middleware (`require_auth`)
- [ ] Valid access token grants access to protected route
- [ ] Missing `Authorization` header returns `401`
- [ ] Malformed header (not `Bearer`) returns `401`
- [ ] Expired access token returns `401`
- [ ] Refresh token used on protected route returns `401`
- [ ] Invalid/tampered token returns `401`

---

*End of analysis.*
