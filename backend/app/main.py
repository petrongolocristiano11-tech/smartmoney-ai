import logging
from contextlib import (
    asynccontextmanager,
)
from backend.app.services.live_trading_worker_runtime import (
    live_trading_worker_runtime,
)
from backend.app.services.live_position_monitor_runtime import (
    live_position_monitor_runtime,
)
from datetime import (
    datetime,
    timezone,
)
from time import perf_counter
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
)
from fastapi.middleware.cors import (
    CORSMiddleware,
)
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.discovered_wallets import (
    router as discovered_wallets_router,
)
from backend.app.api.helius import (
    router as helius_router,
)
from backend.app.api.live import (
    router as live_router,
)
from backend.app.api.live_trading import (
    router as live_trading_router,
)
from backend.app.api.live_platform import (
    router as live_platform_router,
)
from backend.app.api.live_operations import (
    router as live_operations_router,
)
from backend.app.api.paper_autopilot import (
    router as paper_autopilot_router,
)
from backend.app.api.paper_trading import (
    router as paper_trading_router,
)
from backend.app.api.scanner import (
    router as scanner_router,
)
from backend.app.api.solana import (
    router as solana_router,
)
from backend.app.api.tokens import (
    router as tokens_router,
)
from backend.app.api.trades import (
    router as trades_router,
)
from backend.app.api.wallets import (
    router as wallet_router,
)
from backend.app.core.discovery_security import require_automation_key
from backend.app.database.session import get_db
from backend.app.schemas.blockchain_integrity import (
    RawCaptureRetentionPruneRequest,
)
from backend.app.services.raw_blockchain_capture_governance_service import (
    RawCaptureGovernanceError,
    get_raw_capture_readiness,
    preview_raw_capture_retention,
    prune_raw_capture_retention,
    run_raw_capture_canary,
)
from backend.app.services.raw_blockchain_capture_service import (
    get_raw_capture_status,
)
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.error_handlers import (
    register_exception_handlers,
)
from backend.app.core.logging_config import (
    configure_logging,
)
from backend.app.database.session import (
    engine,
)


configure_logging()

logger = logging.getLogger(
    "smartmoney.api"
)


def utc_timestamp() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


@asynccontextmanager
async def lifespan(
    app: FastAPI,
):
    logger.info(
        "application_starting name=%s "
        "version=%s environment=%s",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )

    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

        logger.info(
            "database_startup_check=connected"
        )

    except SQLAlchemyError as exception:
        logger.warning(
            "database_startup_check=unavailable "
            "error_type=%s",
            type(exception).__name__,
        )

    await live_trading_worker_runtime.start()
    await live_position_monitor_runtime.start()

    try:
        yield

    finally:
        await live_position_monitor_runtime.stop()
        await live_trading_worker_runtime.stop()

        engine.dispose()

        logger.info(
            "application_stopped name=%s",
            settings.APP_NAME,
        )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url=(
        "/docs"
        if settings.ENABLE_DOCS
        else None
    ),
    redoc_url=(
        "/redoc"
        if settings.ENABLE_DOCS
        else None
    ),
    openapi_url=(
        "/openapi.json"
        if settings.ENABLE_DOCS
        else None
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=(
        settings.CORS_ALLOW_CREDENTIALS
    ),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Request-ID",
        "X-Process-Time",
        "Content-Disposition",
    ],
)

register_exception_handlers(
    app
)


@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next,
):
    request_id = (
        request.headers.get(
            "X-Request-ID"
        )
        or uuid4().hex
    )

    request.state.request_id = (
        request_id
    )

    started_at = perf_counter()

    try:
        response = await call_next(
            request
        )

    except Exception:
        elapsed = (
            perf_counter()
            - started_at
        )

        logger.exception(
            "request_failed request_id=%s "
            "method=%s path=%s "
            "duration_ms=%.2f",
            request_id,
            request.method,
            request.url.path,
            elapsed * 1000,
        )

        raise

    elapsed = (
        perf_counter()
        - started_at
    )

    response.headers[
        "X-Request-ID"
    ] = request_id

    response.headers[
        "X-Process-Time"
    ] = f"{elapsed:.6f}"

    logger.info(
        "request_complete request_id=%s "
        "method=%s path=%s status=%s "
        "duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed * 1000,
    )

    return response


app.include_router(
    live_router
)

app.include_router(
    tokens_router
)

app.include_router(
    scanner_router
)

app.include_router(
    wallet_router
)

app.include_router(
    solana_router
)

app.include_router(
    helius_router
)

app.include_router(
    trades_router
)

app.include_router(
    discovered_wallets_router
)

app.include_router(
    paper_trading_router
)

app.include_router(
    paper_autopilot_router
)

app.include_router(
    live_trading_router
)
app.include_router(
    live_platform_router
)
app.include_router(
    live_operations_router
)


@app.get(
    "/",
    tags=["System"],
)
def home():
    return {
        "status": "online",
        "project":
            settings.APP_NAME,
        "version":
            settings.APP_VERSION,
        "environment":
            settings.ENVIRONMENT,
        "docs_enabled":
            settings.ENABLE_DOCS,
        "timestamp":
            utc_timestamp(),
    }


@app.get(
    "/health",
    tags=["System"],
)
def health():
    return {
        "status": "ok",
        "service":
            settings.APP_NAME,
        "version":
            settings.APP_VERSION,
        "timestamp":
            utc_timestamp(),
    }


@app.get(
    "/ready",
    tags=["System"],
    responses={
        503: {
            "description":
                "Servizio non pronto",
        },
    },
)
def readiness():
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT 1")
            )

    except SQLAlchemyError as exception:
        logger.warning(
            "readiness_check=failed "
            "dependency=database "
            "error_type=%s",
            type(exception).__name__,
        )

        return JSONResponse(
            status_code=503,
            content={
                "status":
                    "not_ready",
                "dependencies": {
                    "database":
                        "disconnected",
                    "helius":
                        "configured",
                    "solana_rpc":
                        "configured",
                },
                "timestamp":
                    utc_timestamp(),
            },
        )

    return {
        "status": "ready",
        "dependencies": {
            "database":
                "connected",
            "helius":
                "configured",
            "solana_rpc":
                "configured",
        },
        "timestamp":
            utc_timestamp(),
    }

# BEGIN M2 DIRECT RAW CAPTURE STATUS ENDPOINT
@app.get(
    "/integrity/raw-capture/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_status(
    db: Session = Depends(get_db),
):
    return get_raw_capture_status(db)
# END M2 DIRECT RAW CAPTURE STATUS ENDPOINT


# BEGIN M3 RAW CAPTURE GOVERNANCE ENDPOINTS
@app.get(
    "/integrity/raw-capture/readiness",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_readiness(
    db: Session = Depends(get_db),
):
    return get_raw_capture_readiness(db)


@app.post(
    "/integrity/raw-capture/canary",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_raw_capture_canary(
    db: Session = Depends(get_db),
):
    return run_raw_capture_canary(db)


@app.get(
    "/integrity/raw-capture/retention/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_raw_capture_retention_preview(
    provider: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
    ),
    batch_size: int | None = Query(
        default=None,
        ge=1,
        le=10_000,
    ),
    db: Session = Depends(get_db),
):
    try:
        return preview_raw_capture_retention(
            db,
            provider=provider,
            batch_size=batch_size,
        )
    except RawCaptureGovernanceError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception


@app.post(
    "/integrity/raw-capture/retention/prune",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_raw_capture_retention_prune(
    request: RawCaptureRetentionPruneRequest,
    db: Session = Depends(get_db),
):
    try:
        return prune_raw_capture_retention(
            db,
            dry_run=request.dry_run,
            confirmation=request.confirmation,
            provider=request.provider,
            batch_size=request.batch_size,
        )
    except RawCaptureGovernanceError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception
# END M3 RAW CAPTURE GOVERNANCE ENDPOINTS
