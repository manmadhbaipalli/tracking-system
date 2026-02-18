"""FastAPI application factory."""
from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.config import settings
from app.logging_config import setup_logging
from app.middleware.correlation import CorrelationMiddleware
from app.middleware.error_handler import ErrorHandlerMiddleware
from app.middleware.logging import LoggingMiddleware
from app.models import create_tables
from app.config import engine


def create_app() -> FastAPI:
    setup_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Middleware — outermost first (last added = outermost)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)
    app.add_middleware(CorrelationMiddleware)

    # Routers
    app.include_router(auth_router, prefix="/auth", tags=["auth"])

    @app.on_event("startup")
    def on_startup() -> None:
        create_tables(engine)

    @app.get("/health", tags=["health"])
    def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
