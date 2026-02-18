"""Global exception handler middleware."""
import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.exceptions import AppException
from app.logging_config import get_logger
from app.middleware.correlation import get_request_id

logger = get_logger("app.errors")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except AppException as exc:
            request_id = get_request_id()
            logger.warning(
                "Application error",
                extra={
                    "request_id": request_id,
                    "error_code": exc.error_code,
                    "status_code": exc.status_code,
                    "detail": str(exc),
                },
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "error": {
                        "code": exc.error_code,
                        "message": exc.message,
                        "details": exc.details,
                    },
                    "request_id": request_id,
                },
            )
        except Exception as exc:
            request_id = get_request_id()
            logger.error(
                "Unhandled exception",
                extra={
                    "request_id": request_id,
                    "exc_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                },
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "An unexpected error occurred",
                        "details": {},
                    },
                    "request_id": request_id,
                },
            )
