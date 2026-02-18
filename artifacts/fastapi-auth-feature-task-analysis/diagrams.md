# FastAPI Authentication Feature — Architecture Diagrams

**Task ID:** `fastapi-auth-feature-task-analysis`
**Date:** 2026-02-18

This document contains PlantUML sequence diagrams and flow diagrams for the FastAPI authentication system.

---

## 1. Sequence Diagrams

### 1.1 User Registration Flow

```plantuml
@startuml registration_sequence
actor User as user
participant Browser as browser
participant "FastAPI App" as app
participant "Error Handler\nMiddleware" as error_handler
participant "Auth Router" as router
participant "Auth Service" as service
participant "Password\nHasher" as hasher
participant "SQLite DB" as db

user -> browser: 1. Click "Sign Up"
browser -> app: 2. POST /auth/register\n{email, password}

app -> error_handler: 3. Route request

error_handler -> router: 4. Call register()

router -> service: 5. create_user(\n  db, email, password)

service -> hasher: 6. hash_password(\n  password)
hasher --> service: 7. bcrypt_hash

service -> db: 8. INSERT User\n(email, hashed_password)
db --> service: 9. User created (id=123)

service --> router: 10. User object

router --> error_handler: 11. UserResponse (201)

error_handler --> app: 12. 201 Created

app --> browser: 13. JSON response:\n{id: 123, email, ...}

browser --> user: 14. "Account created!"

@enduml
```

### 1.2 Login & Token Generation Flow

```plantuml
@startuml login_sequence
actor User as user
participant Browser as browser
participant "FastAPI App" as app
participant "Auth Router" as router
participant "Auth Service" as service
participant "JWT Encoder" as jwt
participant "SQLite DB" as db

user -> browser: 1. Enter email & password
browser -> app: 2. POST /auth/login\n{email, password}

app -> router: 3. login()

router -> service: 4. authenticate_user(\n  db, email, password)

service -> db: 5. SELECT User\nWHERE email = ?
db --> service: 6. User found

service -> service: 7. verify_password(\n  plain, hashed)
note right: bcrypt constant-time\ncomparison

alt Authentication failed
  service --x router: raise AuthInvalidCredentials
  router --x app: 401 Unauthorized
  app --x browser: Error response
else Authentication successful
  service -> router: 8. User object
  router -> service: 9. create_token_pair(\n  db, user)

  service -> jwt: 10. create_access_token(\n  sub=user_id)
  jwt --> service: 11. access_token (15 min)

  service -> jwt: 12. create_refresh_token(\n  sub=user_id, jti)
  jwt --> service: 13. refresh_token (7 days)

  service -> db: 14. INSERT RefreshToken\n(jti, user_id, expires_at)
  db --> service: 15. Token recorded

  service --> router: 16. (access_token,\nrefresh_token)

  router --> app: 17. TokenResponse (200)

  app --> browser: 18. JSON:\n{access_token, refresh_token}

  browser --> user: 19. Tokens stored\n(localStorage/cookie)
end

@enduml
```

### 1.3 Token Refresh & Rotation Flow

```plantuml
@startuml refresh_sequence
actor User as user
participant Browser as browser
participant "FastAPI App" as app
participant "Auth Router" as router
participant "Auth Service" as service
participant "JWT Decoder" as jwt
participant "SQLite DB" as db

browser -> app: 1. POST /auth/refresh\n{refresh_token}

app -> router: 2. refresh()

router -> service: 3. refresh_tokens(\n  db, refresh_token)

service -> jwt: 4. decode_token(\n  refresh_token,\n  expected_type="refresh")

alt Token invalid or expired
  jwt --x service: raise AuthTokenExpired\nor AuthTokenInvalid
  service --x router: 401 Unauthorized
  router --x app: Error response
  app --x browser: Error JSON
else Token valid
  jwt --> service: 5. {sub, jti, exp, ...}

  service -> db: 6. SELECT RefreshToken\nWHERE jti = ?
  db --> service: 7. Token record

  alt Token revoked or expired
    service --x router: raise AuthTokenRevoked
    router --x app: 401 Unauthorized
    app --x browser: Error response
  else Token valid & not revoked
    service -> db: 8. UPDATE RefreshToken\nSET revoked = TRUE
    note right: Revoke old token\n(prevent replay)
    db --> service: 9. Updated

    service -> service: 10. create_token_pair(\n  db, user)\n(generates new jti)

    service --> router: 11. (new_access_token,\nnew_refresh_token)

    router --> app: 12. TokenResponse (200)

    app --> browser: 13. New token pair

    browser -> browser: 14. Update stored tokens

    browser --> user: 15. Session renewed
  end
end

@enduml
```

### 1.4 Logout Flow

```plantuml
@startuml logout_sequence
actor User as user
participant Browser as browser
participant "FastAPI App" as app
participant "Auth Router" as router
participant "Auth Service" as service
participant "JWT Decoder" as jwt
participant "SQLite DB" as db

browser -> app: 1. POST /auth/logout\n{refresh_token}

app -> router: 2. logout()

router -> service: 3. revoke_refresh_token(\n  db, refresh_token)

service -> jwt: 4. decode_token(\n  refresh_token,\n  expected_type="refresh")

alt Token malformed
  jwt --x service: raise AuthTokenInvalid
  service --x router: 401 Unauthorized
  router --x app: Error response
  app --x browser: Error JSON
else Token valid
  jwt --> service: 5. {sub, jti, ...}

  service -> db: 6. SELECT RefreshToken\nWHERE jti = ?
  db --> service: 7. Token record\n(or null)

  opt Token found
    service -> db: 8. UPDATE RefreshToken\nSET revoked = TRUE
    db --> service: 9. Updated
  end

  service --> router: 10. (void)

  router --> app: 11. MessageResponse (200)

  app --> browser: 12. {message: "Logged out"}

  browser -> browser: 13. Clear stored tokens

  browser --> user: 14. Logged out

  note over browser, db: Future refresh attempt\nwill fail due to revoked=TRUE
end

@enduml
```

---

## 2. State Diagrams

### 2.1 Circuit Breaker State Machine

```plantuml
@startuml circuit_breaker_states
[*] --> CLOSED

CLOSED --> CLOSED: call succeeds\nreset failure_count

CLOSED --> OPEN: failure_count >=\nthreshold

OPEN --> OPEN: call rejected\n(circuit open)

OPEN --> HALF_OPEN: timeout\nelapsed

HALF_OPEN --> HALF_OPEN: call limit\nreached

HALF_OPEN --> CLOSED: probe call\nsucceeds

HALF_OPEN --> OPEN: probe call\nfails

@enduml
```

### 2.2 Authentication State Machine

```plantuml
@startuml auth_states
[*] --> Unauthenticated

Unauthenticated --> Authenticated: POST /auth/login\nPOST /auth/register

Authenticated --> Authenticated: POST /auth/refresh\n(token rotation)

Authenticated --> Unauthenticated: POST /auth/logout\n(revoke refresh token)

note bottom of Unauthenticated
  Cannot access protected resources
  without access token
end note

note bottom of Authenticated
  Has valid access token
  Can refresh using refresh token
end note

@enduml
```

---

## 3. Data Flow Diagrams

### 3.1 Request Processing Pipeline

```plantuml
@startuml request_pipeline
start

:HTTP Request arrives;

:CorrelationMiddleware\n(generate X-Request-ID);

:LoggingMiddleware\n(log "Request started");

:ErrorHandlerMiddleware\n(set exception handler);

if (Route matches?) then (yes)
  :Route Handler\n(business logic);

  if (Exception?) then (yes)
    :Catch Exception\n(log error);

    :Format as JSON\n(ErrorResponse);
  else (no)
    :Return Response\n(success);
  endif
else (no)
  :404 Not Found;
endif

:LoggingMiddleware\n(log "Request finished");

:Add X-Request-ID\nto response header;

:Return HTTP Response;

stop

@enduml
```

### 3.2 Database Entity Relationship

```plantuml
@startuml erd
entity "User" {
  id : int <<PK>>
  --
  email : varchar(255) <<UNIQUE>>
  hashed_password : varchar(255)
  is_active : boolean
  created_at : datetime
}

entity "RefreshToken" {
  id : int <<PK>>
  --
  jti : varchar(36) <<UNIQUE>>
  user_id : int <<FK>>
  expires_at : datetime
  revoked : boolean
  created_at : datetime
}

User ||--o{ RefreshToken : "has many"

@enduml
```

### 3.3 JWT Token Claims Structure

```plantuml
@startuml jwt_structure
card "Access Token" {
  field sub: "user_id"
  field jti: "unique_token_id"
  field type: "access"
  field exp: "expiration_timestamp"
  field iat: "issued_at_timestamp"
}

card "Refresh Token" {
  field sub: "user_id"
  field jti: "unique_token_id"
  field type: "refresh"
  field exp: "expiration_timestamp"
  field iat: "issued_at_timestamp"
}

card "Database\nRefreshToken Record" {
  field id: "primary_key"
  field jti: "matches_token_jti"
  field user_id: "links_to_user"
  field expires_at: "expiration_time"
  field revoked: "logout_flag"
  field created_at: "issued_time"
}

"Access Token" --> "Refresh Token": "same jti"
"Refresh Token" --> "Database\nRefreshToken Record": "lookup by jti"

@enduml
```

---

## 4. Error Handling Flow

### 4.1 Exception Hierarchy & HTTP Mapping

```plantuml
@startuml exception_hierarchy
class AppException <<base>> {
  status_code: int
  error_code: str
  message: str
  details: dict
}

class AuthError {
  status_code = 401
  error_code = "AUTH_ERROR"
}

class AuthInvalidCredentials {
  error_code = "AUTH_INVALID_CREDENTIALS"
}

class AuthTokenExpired {
  error_code = "AUTH_TOKEN_EXPIRED"
}

class AuthTokenInvalid {
  error_code = "AUTH_TOKEN_INVALID"
}

class AuthTokenRevoked {
  error_code = "AUTH_TOKEN_REVOKED"
}

class ValidationError {
  status_code = 422
  error_code = "VALIDATION_ERROR"
}

class ConflictError {
  status_code = 409
  error_code = "CONFLICT"
}

class NotFoundError {
  status_code = 404
  error_code = "NOT_FOUND"
}

class ServiceUnavailableError {
  status_code = 503
  error_code = "SERVICE_UNAVAILABLE"
}

AppException <|-- AuthError
AuthError <|-- AuthInvalidCredentials
AuthError <|-- AuthTokenExpired
AuthError <|-- AuthTokenInvalid
AuthError <|-- AuthTokenRevoked
AppException <|-- ValidationError
AppException <|-- ConflictError
AppException <|-- NotFoundError
AppException <|-- ServiceUnavailableError

@enduml
```

### 4.2 Error Response Format

```plantuml
@startuml error_response
start

:Exception raised\nin route;

:ErrorHandlerMiddleware\ncatches exception;

if (Exception type?) then (AppException)
  :Extract:\nstatus_code\nerror_code\nmessage\ndetails;
else if (RequestValidationError)
  :status_code = 422\nerror_code = "VALIDATION_ERROR";
else (Other Exception)
  :status_code = 500\nerror_code = "INTERNAL_ERROR";
endif

:Get correlation_id\nfrom ContextVar;

:Build ErrorResponse JSON:\n{\n  error: {\n    code,\n    message,\n    details\n  },\n  request_id: correlation_id\n};

:Log exception\n(with traceback\nif ERROR level);

:Return JSONResponse\nwith status_code;

stop

@enduml
```

---

## 5. Middleware Execution Order

```plantuml
@startuml middleware_order
box "HTTP Request" #FFEEEE
    participant Request
end box

box "Starlette/FastAPI" #EEEEFF
    participant CorrelationMiddleware as Correlation
    participant LoggingMiddleware as Logging
    participant ErrorHandlerMiddleware as ErrorHandler
    participant RouteHandler as Route
end box

box "HTTP Response" #EEFFEE
    participant ResponseOut
end box

Request -> Correlation: 1. Incoming request

activate Correlation
Correlation -> Correlation: Generate/extract\nX-Request-ID

Correlation -> Logging: 2. pass to next

deactivate Correlation

activate Logging
Logging -> Logging: Log "Request started"\nwith timing

Logging -> ErrorHandler: 3. pass to next

deactivate Logging

activate ErrorHandler
ErrorHandler -> Route: 4. pass to next

activate Route
Route -> Route: Process request\nCall route handler
Route --> Route: Return response\nor raise exception

deactivate Route

ErrorHandler -> ErrorHandler: Catch exceptions\nFormat JSON

deactivate ErrorHandler

activate Logging
Logging -> Logging: Log "Request finished"\nwith duration

deactivate Logging

activate Correlation
Correlation -> Correlation: Add X-Request-ID\nto response headers

Correlation -> ResponseOut: 5. Final response

deactivate Correlation

ResponseOut -> ResponseOut: Send to client

@enduml
```

---

## 6. Token Lifecycle

```plantuml
@startuml token_lifecycle
start

:User logs in;

:✅ Create access token\n(15 min TTL);

:✅ Create refresh token\n(7 day TTL);

:✅ Store RefreshToken\nrecord in DB;

:Return token pair\nto client;

:Client stores tokens\n(localStorage, etc);

while (Access token valid?) is (yes)
  :Use access token\nfor API calls;

  if (Approaching expiry?) then (yes)
    :POST /auth/refresh\nwith refresh_token;

    if (Valid & not revoked?) then (yes)
      :✅ Issue new access token\n(same jti);

      :✅ Revoke old refresh token\n(set revoked=true);

      :✅ Issue new refresh token\n(new jti);

      :Update client tokens;
    else (no)
      :❌ Auth error\n(401 Unauthorized);

      :Force re-login;

      stop
    endif
  else (no)
    :Continue using\naccess token;
  endif
endwhile (no)

:Token expired;

:POST /auth/logout\nwith refresh_token;

:✅ Revoke refresh token\n(set revoked=true);

:Clear tokens on client;

:Session ends;

stop

@enduml
```

---

## 7. Logging Flow

```plantuml
@startuml logging_flow
participant Code as "App Code"
participant Logger as "Python Logger"
participant JsonFormatter as "JsonFormatter"
participant Handler as "StreamHandler"
participant Output as "stdout"

Code -> Logger: logger.info(\n  "message",\n  extra={\n    request_id,\n    user_id,\n    ...\n  })

Logger -> JsonFormatter: LogRecord\n(with extra fields)

JsonFormatter -> JsonFormatter: Build dict:\n- timestamp\n- level\n- name\n- message\n- extra fields

JsonFormatter -> Handler: JSON string

Handler -> Handler: buffering (if enabled)

Handler -> Output: Write to stdout

Output -> Output: Collected by\ncontainer/syslog\nfor forwarding

@enduml
```

---

## 8. Password Hashing & Verification

```plantuml
@startuml password_security
start

:User enters password\n"SecurePass123!";

:Client sends over HTTPS;

if (Operation?) then (Registration)
  :hash_password(\n  "SecurePass123!");

  :Use bcrypt:\ngenerate salt\nderived key\n(slow, ~0.5s);

  :Store hashed value\nin database;

  :Never store plaintext;
else (Login)
  :Get plaintext from request;

  :Fetch hashed password\nfrom database;

  :verify_password(\n  plaintext,\n  hashed);

  note right
    passlib uses constant-time\ncomparison to prevent\ntiming attacks
  end note

  if (Match?) then (yes)
    :✅ Authentication success;
  else (no)
    :❌ Authentication failure;

    note right
      Same error for:\n- wrong password\n- user not found\n(no enumeration)
    end note
  endif
endif

stop

@enduml
```

---

## 9. Configuration & Environment

```plantuml
@startuml configuration
card "Environment\nVariables" {
  SECRET_KEY
  DATABASE_URL
  ACCESS_TOKEN_EXPIRE_MINUTES
  REFRESH_TOKEN_EXPIRE_DAYS
  LOG_LEVEL
  DEBUG
}

card "Pydantic\nSettings" {
  model_config = SettingsConfigDict(
    env_file=".env"
  )
}

card "Application" {
  config.settings
  JWT algorithms
  Database engine
  Logging level
}

"Environment\nVariables" --> "Pydantic\nSettings": load from .env

"Pydantic\nSettings" --> Application: singleton\ninstance

@enduml
```

---

## 10. Deployment Architecture

```plantuml
@startuml deployment
package "Client" {
  [Web Browser]
  [Mobile App]
}

package "Load Balancer" {
  [Nginx/AWS ALB]
}

package "Application Servers" {
  [Uvicorn Worker 1] as W1
  [Uvicorn Worker 2] as W2
  [Uvicorn Worker 3] as W3
}

package "Cache & Data" {
  [Redis\n(optional)]
  [PostgreSQL\nDatabase]
  [SQLite\n(dev only)]
}

[Web Browser] --> [Nginx/AWS ALB]: HTTPS
[Mobile App] --> [Nginx/AWS ALB]: HTTPS

[Nginx/AWS ALB] --> W1: Route requests
[Nginx/AWS ALB] --> W2: Route requests
[Nginx/AWS ALB] --> W3: Route requests

W1 --> [PostgreSQL\nDatabase]: DB queries
W2 --> [PostgreSQL\nDatabase]: DB queries
W3 --> [PostgreSQL\nDatabase]: DB queries

note on link
  Each worker has\nindependent circuit\nbreaker state\n(limitation)
end note

W1 -.-> [Redis\n(optional)]: Shared circuit\nbreaker state

@enduml
```

---

## Summary

These diagrams illustrate:

1. **Sequence diagrams** — User interactions and system flows
2. **State diagrams** — Circuit breaker and authentication states
3. **Data flow** — Request processing, database schema, tokens
4. **Error handling** — Exception hierarchy and response formatting
5. **Middleware** — Execution order and request processing
6. **Token lifecycle** — From creation to expiration
7. **Security** — Password hashing and verification
8. **Configuration** — Environment setup
9. **Deployment** — Production architecture

All diagrams are in PlantUML format and can be rendered using:
- PlantUML online editor: https://www.plantuml.com/plantuml/uml/
- VS Code PlantUML extension
- GitHub (renders PlantUML in markdown)

---

**Diagrams completed:** 2026-02-18
