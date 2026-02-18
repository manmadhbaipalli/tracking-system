# FastAPI Application — Design

**Task:** fastapi-app-design
**Phase:** design
**Date:** 2026-02-18
**Depends on:** fastapi-app-analysis

---

## 1. Approach

This is a greenfield implementation of a production-ready FastAPI application. All 22 files must be created. The design follows the analysis recommendations with the following strategic choices for each open question:

| Open Question | Decision | Rationale |
|---------------|----------|-----------|
| Token storage | DB-stored refresh tokens (not cookies) | Simpler for API clients; XSS risk noted in README |
| Multi-worker circuit breaker | In-process state | Scope constraint; noted as known limitation |
| Async vs sync DB | Sync SQLAlchemy sessions | Simpler, avoids asyncio complexity; sufficient for SQLite + single-worker dev |
| Refresh token lifetime | 7 days (configurable) | Sensible default; overridable via env var |
| User model | `id`, `email`, `hashed_password`, `is_active`, `created_at` | Minimal but production-useful fields |
| Logout scope | Single session (provided refresh token only) | Predictable; document "logout all" as future work |
| Circuit breaker fallback | 503 ServiceUnavailableError | Consistent with error framework; cached response out of scope |
| JSON logging | Custom stdlib formatter (no extra dep) | Keeps requirements minimal; `python-json-logger` is optional |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  HTTP Client                                                     │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  Starlette Middleware Stack (applied outermost-first)           │
│  1. CorrelationMiddleware  — injects X-Correlation-ID           │
│  2. LoggingMiddleware      — logs request + response            │
│  3. ErrorHandlerMiddleware — catches exceptions, formats JSON   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│  FastAPI Application                                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  auth/router.py                                          │   │
│  │  POST /auth/register                                     │   │
│  │  POST /auth/login                                        │   │
│  │  POST /auth/refresh                                      │   │
│  │  POST /auth/logout                                       │   │
│  └───────────────────┬─────────────────────────────────────┘   │
│                      │                                          │
│  ┌───────────────────▼─────────────────────────────────────┐   │
│  │  auth/service.py  (business logic)                       │   │
│  │    ├── auth/jwt.py  (token encode/decode)                │   │
│  │    └── models.py   (User, RefreshToken ORM)              │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘

Shared: config.py, exceptions.py, logging_config.py, circuit_breaker.py
```

### Middleware Registration Order in `main.py`

Starlette applies middleware in **reverse** order of `add_middleware` calls. To achieve the execution order `Correlation → Logging → ErrorHandler → RouteHandler`, register as:

```python
app.add_middleware(ErrorHandlerMiddleware)   # registered first → innermost
app.add_middleware(LoggingMiddleware)
app.add_middleware(CorrelationMiddleware)    # registered last → outermost
```

---

## 3. File-by-File Design

### 3.1 `requirements.txt`

```
fastapi>=0.111.0,<1.0
uvicorn[standard]>=0.29.0,<1.0
sqlalchemy>=2.0.0,<3.0
pydantic[email]>=2.0.0,<3.0
pydantic-settings>=2.0.0,<3.0
python-jose[cryptography]>=3.3.0,<4.0
passlib[bcrypt]>=1.7.4,<2.0
python-multipart>=0.0.9,<1.0
pytest>=8.0.0,<9.0
httpx>=0.27.0,<1.0
pytest-asyncio>=0.23.0,<1.0
```

No `python-json-logger` — custom formatter used in `logging_config.py`.

---

### 3.2 `app/__init__.py`

Empty package marker.

---

### 3.3 `app/config.py`

Uses Pydantic v2 `BaseSettings` to load configuration from environment variables with sensible defaults.

**Class: `Settings(BaseSettings)`**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `database_url` | `str` | `"sqlite:///./app.db"` | SQLAlchemy connection string |
| `secret_key` | `SecretStr` | (required) | JWT signing secret — no default forces explicit config |
| `algorithm` | `str` | `"HS256"` | JWT algorithm; pinned to HS256 |
| `access_token_expire_minutes` | `int` | `15` | Short-lived access token TTL |
| `refresh_token_expire_days` | `int` | `7` | Refresh token TTL |
| `log_level` | `str` | `"INFO"` | Python logging level name |
| `app_name` | `str` | `"FastAPI App"` | Used in OpenAPI title |
| `debug` | `bool` | `False` | Enables SQLAlchemy echo, verbose logs |

```python
# model_config replaces class Config in Pydantic v2
model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

**Module-level singleton:**
```python
settings = Settings()
```

**DB engine + session factory:**
```python
engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

The `check_same_thread=False` argument is only safe for SQLite because each request gets its own session via dependency injection; it must be omitted for PostgreSQL.

---

### 3.4 `app/models.py`

SQLAlchemy 2.0 ORM models using the `DeclarativeBase` approach.

**`Base = DeclarativeBase()`** — all models inherit from this.

#### Model: `User`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `Integer` | PK, autoincrement |
| `email` | `String(255)` | unique, not null, indexed |
| `hashed_password` | `String(255)` | not null |
| `is_active` | `Boolean` | not null, default=True |
| `created_at` | `DateTime` | not null, server_default=now() |

Relationship: `refresh_tokens` → one-to-many with `RefreshToken`, `cascade="all, delete-orphan"`.

#### Model: `RefreshToken`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `Integer` | PK, autoincrement |
| `jti` | `String(36)` | unique, not null, indexed (UUID) |
| `user_id` | `Integer` | FK → `users.id`, not null |
| `expires_at` | `DateTime` | not null |
| `revoked` | `Boolean` | not null, default=False |
| `created_at` | `DateTime` | not null, server_default=now() |

**Module-level helper:**
```python
def create_tables(engine) -> None:
    Base.metadata.create_all(bind=engine)
```

---

### 3.5 `app/schemas.py`

All Pydantic v2 models. Use `model_config = ConfigDict(from_attributes=True)` on response models.

#### Request schemas

```python
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class LogoutRequest(BaseModel):
    refresh_token: str
```

#### Response schemas

```python
class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    is_active: bool
    created_at: datetime

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"

class MessageResponse(BaseModel):
    message: str
```

#### Error schemas

```python
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)

class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str
```

`ErrorResponse` is used as the consistent error body shape by the error handler middleware.

---

### 3.6 `app/exceptions.py`

All custom exceptions inherit from a common `AppException` base that carries HTTP status, error code, and optional details.

```python
class AppException(Exception):
    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


class AuthError(AppException):
    status_code = 401
    error_code = "AUTH_ERROR"

class AuthInvalidCredentials(AuthError):
    error_code = "AUTH_INVALID_CREDENTIALS"

class AuthTokenExpired(AuthError):
    error_code = "AUTH_TOKEN_EXPIRED"

class AuthTokenInvalid(AuthError):
    error_code = "AUTH_TOKEN_INVALID"

class AuthTokenRevoked(AuthError):
    error_code = "AUTH_TOKEN_REVOKED"

class ValidationError(AppException):
    status_code = 422
    error_code = "VALIDATION_ERROR"

class NotFoundError(AppException):
    status_code = 404
    error_code = "NOT_FOUND"

class ConflictError(AppException):
    status_code = 409
    error_code = "CONFLICT"

class ServiceUnavailableError(AppException):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
```

`ConflictError` is needed for "email already registered" (409, not 422).

---

### 3.7 `app/logging_config.py`

Configures the root Python logger with a custom JSON formatter.

**`JsonFormatter(logging.Formatter)`**

`format(record) -> str`:
- Build a dict with: `timestamp` (ISO 8601 from `record.created`), `level`, `name`, `message`.
- Merge any extra fields attached to the record (e.g. `request_id`, `user_id`, `endpoint`, `duration_ms`).
- Return `json.dumps(log_dict)`.

**`setup_logging(level: str = "INFO") -> None`**:
```python
def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
```

Called once at application startup in `main.py`.

**Module-level logger factory:**
```python
def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

---

### 3.8 `app/middleware/__init__.py`

Empty package marker.

---

### 3.9 `app/middleware/correlation.py`

Injects a correlation/request ID into every request and response.

**ContextVar:**
```python
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
```

**`CorrelationMiddleware(BaseHTTPMiddleware)`**

`async def dispatch(request, call_next)`:
1. Read `X-Correlation-ID` from request headers; if absent generate `uuid.uuid4().hex`.
2. Set `correlation_id_var` with the generated/received ID.
3. `response = await call_next(request)`.
4. Attach `X-Correlation-ID` to response headers.
5. Return response.

**Public accessor:**
```python
def get_correlation_id() -> str:
    return correlation_id_var.get()
```

This function is imported by the logging middleware and the JSON formatter to include `request_id` in every log line.

---

### 3.10 `app/middleware/logging.py`

Logs structured request/response info for every HTTP request.

**`LoggingMiddleware(BaseHTTPMiddleware)`**

`async def dispatch(request, call_next)`:
1. Record `start_time = time.perf_counter()`.
2. Extract `correlation_id = get_correlation_id()`.
3. Log "request received" at INFO: `method`, `path`, `query_string`, `request_id`.
4. `response = await call_next(request)`.
5. Compute `duration_ms = (time.perf_counter() - start_time) * 1000`.
6. Log "request completed" at INFO: `method`, `path`, `status_code`, `duration_ms`, `request_id`.
   - Log at WARNING if `status_code >= 400`, ERROR if `>= 500`.
7. Return response.

Note: `user_id` is not available at middleware level (auth happens inside the route). User ID is logged by `auth/service.py` at the point of authentication, not in the middleware.

---

### 3.11 `app/middleware/error_handler.py`

Catches all exceptions and converts them to the consistent `ErrorResponse` JSON format.

**`ErrorHandlerMiddleware(BaseHTTPMiddleware)`**

`async def dispatch(request, call_next)`:

```
try:
    return await call_next(request)
except AppException as exc:
    log.error("App exception", extra={...exc fields...})
    return JSONResponse(status_code=exc.status_code, content=ErrorResponse(...).model_dump())
except RequestValidationError as exc:
    log.warning("Validation error", ...)
    return JSONResponse(status_code=422, content=ErrorResponse(...).model_dump())
except HTTPException as exc:
    log.warning("HTTP exception", ...)
    return JSONResponse(status_code=exc.status_code, content=ErrorResponse(...).model_dump())
except Exception as exc:
    log.exception("Unhandled exception")   # logs full traceback
    return JSONResponse(status_code=500, content=ErrorResponse(
        error=ErrorDetail(code="INTERNAL_ERROR", message="An unexpected error occurred"),
        request_id=get_correlation_id()
    ).model_dump())
```

**Key invariant:** The `except Exception` branch MUST log the full traceback (`log.exception`) but MUST NOT include it in the HTTP response body.

**Override FastAPI's default exception handlers** in `main.py`:
```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    # delegate to error format
```

---

### 3.12 `app/auth/__init__.py`

Empty package marker.

---

### 3.13 `app/auth/jwt.py`

All JWT operations. Uses `python-jose`.

**Functions:**

```python
def create_access_token(subject: str, jti: str | None = None) -> str:
    """
    Create a short-lived access token.
    Claims: sub=subject, jti=jti or uuid4(), exp, iat, type="access"
    """

def create_refresh_token(subject: str, jti: str) -> str:
    """
    Create a long-lived refresh token.
    Claims: sub=subject, jti=jti, exp, iat, type="refresh"
    """

def decode_token(token: str, expected_type: str) -> dict:
    """
    Decode and validate a token.
    - Uses algorithms=["HS256"] explicitly (prevents alg:none attack)
    - Raises AuthTokenExpired if expired
    - Raises AuthTokenInvalid if signature fails or type mismatch
    Returns the full claims dict.
    """
```

**Implementation details:**
- Secret from `settings.secret_key.get_secret_value()` — `SecretStr` requires explicit unwrap.
- `jti` is a UUID4 hex string; used as the primary key for refresh token DB records.
- `exp` is computed from `datetime.utcnow()` + timedelta; `python-jose` handles this automatically when passed a `timedelta`.

---

### 3.14 `app/auth/service.py`

Business logic layer. Depends on SQLAlchemy session, ORM models, jwt.py, and passlib.

**Dependency:**
```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

**Functions:**

```python
def hash_password(password: str) -> str: ...

def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison via passlib."""

def get_user_by_email(db: Session, email: str) -> User | None: ...

def create_user(db: Session, email: str, password: str) -> User:
    """
    1. Check for existing user → raise ConflictError if found.
    2. Hash password.
    3. Create User ORM object, db.add, db.commit, db.refresh.
    4. Return user.
    """

def authenticate_user(db: Session, email: str, password: str) -> User:
    """
    1. Fetch user by email.
    2. Verify password.
    3. Raise AuthInvalidCredentials if either fails (same error for both — no user enumeration).
    4. Return user.
    """

def create_token_pair(db: Session, user: User) -> tuple[str, str]:
    """
    1. Generate jti = uuid4().hex
    2. access_token = create_access_token(str(user.id), jti)
    3. refresh_token = create_refresh_token(str(user.id), jti)
    4. Store RefreshToken ORM record in DB.
    5. Return (access_token, refresh_token)
    """

def refresh_tokens(db: Session, refresh_token_str: str) -> tuple[str, str]:
    """
    1. decode_token(refresh_token_str, expected_type="refresh")
    2. Look up RefreshToken by jti in DB.
    3. Raise AuthTokenRevoked if revoked=True or not found.
    4. Raise AuthTokenExpired if expires_at < now.
    5. Revoke old token (revoked=True), commit.
    6. create_token_pair → new pair.
    7. Return new pair.
    """

def revoke_refresh_token(db: Session, refresh_token_str: str) -> None:
    """
    1. decode_token(refresh_token_str, expected_type="refresh") — if invalid, silently pass or raise based on spec.
    2. Look up by jti, set revoked=True if found.
    3. Commit.
    Decision: raise AuthTokenInvalid if token is malformed; silently succeed if token is valid but already revoked (idempotent logout).
    """
```

---

### 3.15 `app/auth/router.py`

FastAPI `APIRouter` with prefix `/auth` and tag `auth`.

**Security scheme declaration** (for OpenAPI):
```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)
```

**Endpoints:**

#### `POST /auth/register`
- **Request:** `RegisterRequest`
- **Response:** `UserResponse` (201)
- **Errors:** 409 ConflictError (email taken), 422 ValidationError (invalid email/short password)
- **Logic:** `service.create_user(db, body.email, body.password)`

#### `POST /auth/login`
- **Request:** `LoginRequest`
- **Response:** `TokenResponse` (200)
- **Errors:** 401 AuthInvalidCredentials
- **Logic:** `user = service.authenticate_user(...)`, `service.create_token_pair(db, user)`
- **Note:** Accepts JSON body (`LoginRequest`), not `OAuth2PasswordRequestForm`, to keep the API consistent and avoid form encoding.

#### `POST /auth/refresh`
- **Request:** `RefreshRequest`
- **Response:** `TokenResponse` (200)
- **Errors:** 401 AuthTokenInvalid, AuthTokenRevoked, AuthTokenExpired
- **Logic:** `service.refresh_tokens(db, body.refresh_token)`

#### `POST /auth/logout`
- **Request:** `LogoutRequest`
- **Response:** `MessageResponse` (200) `{"message": "Logged out successfully"}`
- **Errors:** 401 AuthTokenInvalid (malformed token)
- **Logic:** `service.revoke_refresh_token(db, body.refresh_token)`

**Dependency injection:**
```python
@router.post("/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)): ...
```

---

### 3.16 `app/circuit_breaker.py`

Thread-safe state machine for wrapping calls to external services.

**States (enum):**
```python
class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
```

**`CircuitBreaker` class:**

```python
class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,   # seconds to stay OPEN before HALF_OPEN
        half_open_max_calls: int = 1,      # how many test calls in HALF_OPEN
    ): ...
```

**Internal state:**
- `_state: CircuitState = CLOSED`
- `_failure_count: int = 0`
- `_last_failure_time: float | None = None`
- `_lock: threading.Lock` — protects state transitions

**Key method: `call(func, *args, fallback=None, **kwargs)`**

```
acquire lock
if OPEN:
    if elapsed >= recovery_timeout: transition to HALF_OPEN
    else: raise ServiceUnavailableError (or return fallback if provided)

if HALF_OPEN:
    allow the call through (trial call)
    on success: transition to CLOSED
    on failure: transition to OPEN

if CLOSED:
    call func
    on success: reset failure_count
    on failure: increment failure_count; if >= threshold → OPEN
```

**Properties:**
```python
@property
def state(self) -> CircuitState: ...
@property
def failure_count(self) -> int: ...
```

**Decorator convenience:**
```python
def circuit_breaker(cb_instance: CircuitBreaker):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return cb_instance.call(func, *args, **kwargs)
        return wrapper
    return decorator
```

---

### 3.17 `app/main.py`

Application factory and wiring.

```python
def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Register middleware (reverse of desired execution order)
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(CorrelationMiddleware)

    # Include routers
    app.include_router(auth_router, prefix="/auth", tags=["auth"])

    # Create DB tables
    create_tables(engine)

    # Health check
    @app.get("/health", tags=["health"])
    def health_check():
        return {"status": "ok"}

    return app

app = create_app()
```

**OpenAPI security scheme** (for Swagger Bearer auth):
```python
app = FastAPI(
    ...,
    openapi_tags=[{"name": "auth", "description": "Authentication endpoints"}],
)
```

Swagger Bearer auth is self-documenting via the `OAuth2PasswordBearer` declared in `router.py`.

---

## 4. API Design

### Endpoint Summary

| Method | Path | Request Body | Success Response | Auth Required |
|--------|------|-------------|-----------------|---------------|
| POST | /auth/register | `RegisterRequest` | 201 `UserResponse` | No |
| POST | /auth/login | `LoginRequest` | 200 `TokenResponse` | No |
| POST | /auth/refresh | `RefreshRequest` | 200 `TokenResponse` | No |
| POST | /auth/logout | `LogoutRequest` | 200 `MessageResponse` | No (token in body) |
| GET | /health | — | 200 `{"status": "ok"}` | No |

### Error Response Format

Every error returns:
```json
{
  "error": {
    "code": "AUTH_INVALID_CREDENTIALS",
    "message": "Invalid email or password",
    "details": {}
  },
  "request_id": "550e8400e29b41d4a716446655440000"
}
```

### HTTP Status → Error Code Mapping

| Status | Code | Trigger |
|--------|------|---------|
| 400 | `BAD_REQUEST` | Generic bad request |
| 401 | `AUTH_INVALID_CREDENTIALS` | Wrong email/password |
| 401 | `AUTH_TOKEN_EXPIRED` | Access/refresh token expired |
| 401 | `AUTH_TOKEN_INVALID` | Malformed/tampered token |
| 401 | `AUTH_TOKEN_REVOKED` | Already-logged-out token used |
| 404 | `NOT_FOUND` | Resource not found |
| 409 | `CONFLICT` | Email already registered |
| 422 | `VALIDATION_ERROR` | Pydantic request validation failure |
| 500 | `INTERNAL_ERROR` | Unhandled exception |
| 503 | `SERVICE_UNAVAILABLE` | Circuit breaker OPEN |

---

## 5. Data Model

### Entity-Relationship

```
User (1) ─────────────────────────── (N) RefreshToken
 id PK                                    id PK
 email UNIQUE                             jti UNIQUE (UUID)
 hashed_password                          user_id FK → users.id
 is_active                                expires_at
 created_at                               revoked BOOL
                                          created_at
```

### JWT Payload Structure

**Access token:**
```json
{
  "sub": "42",
  "jti": "550e8400e29b41d4a716446655440000",
  "type": "access",
  "exp": 1739880900,
  "iat": 1739879000
}
```

**Refresh token:**
```json
{
  "sub": "42",
  "jti": "550e8400e29b41d4a716446655440000",
  "type": "refresh",
  "exp": 1740484700,
  "iat": 1739879000
}
```

Note: Access and refresh tokens share the same `jti`. This links the access token to a DB-tracked refresh token and simplifies revocation lookup.

---

## 6. Test Strategy

### `tests/conftest.py`

Fixtures:
- `engine` (session-scoped): `create_engine("sqlite:///:memory:")`, calls `create_tables(engine)`.
- `db` (function-scoped): yields a session from `SessionLocal` bound to the test engine; rolls back after each test.
- `client` (function-scoped): `TestClient(app)` with `get_db` dependency overridden to use the test `db` session.
- `test_user` (function-scoped): pre-registered user created via `service.create_user`.
- `auth_headers` (function-scoped): calls `/auth/login`, returns `{"Authorization": "Bearer <access_token>"}`.

Dependency override pattern:
```python
def override_get_db():
    yield db_session

app.dependency_overrides[get_db] = override_get_db
```

### `tests/test_auth.py`

| Test | Assertion |
|------|-----------|
| `test_register_success` | 201, returns user email, hashed_password not exposed |
| `test_register_duplicate_email` | 409, error code CONFLICT |
| `test_register_invalid_email` | 422, error code VALIDATION_ERROR |
| `test_register_short_password` | 422 |
| `test_login_success` | 200, returns access_token and refresh_token |
| `test_login_wrong_password` | 401, AUTH_INVALID_CREDENTIALS |
| `test_login_unknown_email` | 401, AUTH_INVALID_CREDENTIALS (no user enumeration) |
| `test_refresh_success` | 200, new token pair; old refresh token revoked |
| `test_refresh_revoked_token` | 401, AUTH_TOKEN_REVOKED |
| `test_refresh_invalid_token` | 401, AUTH_TOKEN_INVALID |
| `test_logout_success` | 200, message response |
| `test_logout_then_refresh` | 401, AUTH_TOKEN_REVOKED (can't refresh after logout) |
| `test_logout_invalid_token` | 401, AUTH_TOKEN_INVALID |

### `tests/test_circuit_breaker.py`

| Test | Assertion |
|------|-----------|
| `test_initial_state_closed` | `cb.state == CircuitState.CLOSED` |
| `test_success_does_not_change_state` | State remains CLOSED after successful calls |
| `test_failures_open_circuit` | After `threshold` failures, `cb.state == OPEN` |
| `test_open_raises_service_unavailable` | Calling `cb.call(...)` when OPEN raises `ServiceUnavailableError` |
| `test_open_returns_fallback` | With fallback kwarg, returns fallback instead of raising |
| `test_half_open_after_timeout` | After `recovery_timeout` seconds, state transitions to HALF_OPEN |
| `test_half_open_success_closes` | Successful call in HALF_OPEN → CLOSED |
| `test_half_open_failure_reopens` | Failing call in HALF_OPEN → OPEN |
| `test_decorator_usage` | `@circuit_breaker(cb)` wraps a function correctly |
| `test_failure_count_resets_on_close` | After successful HALF_OPEN → CLOSED, `failure_count == 0` |

For time-based tests (`test_half_open_after_timeout`), use `unittest.mock.patch` to mock `time.monotonic()` rather than sleeping.

### `tests/test_middleware.py`

| Test | Assertion |
|------|-----------|
| `test_correlation_id_generated` | Response has `X-Correlation-ID` header |
| `test_correlation_id_propagated` | Sending `X-Correlation-ID` in request → same ID in response |
| `test_error_response_format` | 404 response has `error.code`, `error.message`, `request_id` |
| `test_internal_error_no_traceback` | Simulated 500 response body does not contain stack trace text |
| `test_validation_error_format` | Pydantic validation error returns 422 with consistent format |
| `test_request_id_in_error_response` | `request_id` in error body matches `X-Correlation-ID` header |

---

## 7. Sequence of Changes (Implementation Order)

The implementation agent should create files in this order to avoid import errors during development:

```
1.  requirements.txt              — no dependencies
2.  app/__init__.py               — empty
3.  app/config.py                 — all others import settings
4.  app/exceptions.py             — imported by middleware and services
5.  app/logging_config.py         — imported by middleware
6.  app/models.py                 — imported by service
7.  app/schemas.py                — imported by router
8.  app/auth/__init__.py          — empty
9.  app/auth/jwt.py               — imported by service
10. app/auth/service.py           — imported by router
11. app/auth/router.py            — imported by main
12. app/middleware/__init__.py    — empty
13. app/middleware/correlation.py — imported by logging middleware
14. app/middleware/logging.py     — imported by main
15. app/middleware/error_handler.py — imported by main
16. app/circuit_breaker.py        — standalone, no app dependencies
17. app/main.py                   — wires everything together
18. tests/__init__.py             — empty
19. tests/conftest.py             — test infrastructure
20. tests/test_auth.py            — auth endpoint tests
21. tests/test_circuit_breaker.py — circuit breaker unit tests
22. tests/test_middleware.py      — middleware integration tests
23. README.md                     — documentation
```

---

## 8. Security Checklist

- [ ] `settings.secret_key` is `SecretStr`; `.get_secret_value()` used only in `jwt.py`
- [ ] JWT decode always passes `algorithms=["HS256"]` explicitly
- [ ] Password hashing uses `passlib` bcrypt; plaintext never stored or logged
- [ ] Login error is identical for "email not found" and "wrong password" (no user enumeration)
- [ ] Stack traces logged but not returned in HTTP responses
- [ ] Refresh token rotation on every `/auth/refresh` call
- [ ] Refresh token `revoked` flag checked on DB lookup before issuing new tokens
- [ ] `check_same_thread=False` SQLite arg documented as dev-only

---

## 9. Open Items for Implementation Agent

1. **`pytest.ini` / `pyproject.toml`** — not in the file constraint list but `pytest-asyncio` needs `asyncio_mode = "auto"` if async tests are used. Since all endpoints are sync SQLAlchemy, sync `TestClient` should suffice; `pytest-asyncio` is in requirements as a safety net.

2. **`/auth/logout` error handling** — if the provided refresh token JWT is structurally valid but not found in the DB (e.g., it was never stored), treat as successful logout (idempotent) rather than an error. Only raise `AuthTokenInvalid` for malformed JWTs.

3. **Token cleanup** — The `RefreshToken` table will grow over time. The implementation should note this in the README and optionally add a periodic cleanup of expired+revoked tokens. Not required for passing tests.

4. **PostgreSQL readiness** — Remove `connect_args={"check_same_thread": False}` when `database_url` starts with `postgresql://`. This can be handled by inspecting the URL scheme in `config.py`:
   ```python
   connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
   ```

5. **`README.md` content** — Should cover: installation, environment variables reference, running the dev server, running tests, API overview.
