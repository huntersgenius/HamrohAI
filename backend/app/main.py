"""FastAPI application entry point."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import sqlalchemy as sa
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.schemas.common import ErrorResponse, HealthResponse

log = get_logger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info(
        "app.starting",
        env=settings.ENV,
        version=VERSION,
        data_residency=settings.DATA_RESIDENCY_REGION,
    )
    try:
        from app.services.storage import ensure_bucket

        await ensure_bucket()
    except Exception as exc:  # noqa: BLE001 - storage must not block boot
        log.warning("app.storage_unavailable", error=str(exc))
    yield
    await dispose_engine()
    log.info("app.stopped")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=VERSION,
    description=(
        "Hamroh — chronic illness home-monitoring and online doctor consultation "
        "platform for Uzbekistan."
    ),
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

if settings.trusted_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id and emit one structured access log per request."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    log.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
    )
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(code=exc.code, message=exc.message, details=exc.details).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            code="validation_error",
            message="request validation failed",
            # Errors can carry non-serialisable context objects; keep the shape flat.
            details={
                "errors": [
                    {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
                    for e in exc.errors()
                ]
            },
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak an internal message to a client of a medical application.
    log.error("http.unhandled", path=request.url.path, error=str(exc), exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(code="internal_error", message="internal server error").model_dump(),
    )


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health() -> HealthResponse:
    database = "ok"
    try:
        async with get_sessionmaker()() as session:
            await session.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        log.error("health.db_failed", error=str(exc))
        database = "error"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        env=settings.ENV,
        version=VERSION,
        data_residency_region=settings.DATA_RESIDENCY_REGION,
        database=database,
        time=datetime.now(UTC),
    )


app.include_router(api_router, prefix=settings.API_V1_PREFIX)
