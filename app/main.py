"""FastAPI application factory."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.config import engine, settings
from app.logging_config import setup_logging
from app.middleware.correlation import CorrelationMiddleware
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.logging import LoggingMiddleware
from app.models import create_tables


def create_app() -> FastAPI:
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        create_tables(engine)
        yield

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Middleware registration (Starlette applies in reverse order of add_middleware).
    # Desired execution order: Correlation → Logging → ErrorHandler → Route
    app.add_middleware(ErrorHandlerMiddleware)  # innermost: catches route exceptions
    app.add_middleware(LoggingMiddleware)       # middle: logs req/response with correlation ID
    app.add_middleware(CorrelationMiddleware)   # outermost: sets request ID before all others

    # Routers
    app.include_router(auth_router, prefix="/auth", tags=["auth"])

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
