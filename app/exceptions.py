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
