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
    CanonicalMaterializationExecuteRequest,
    CanonicalParserPromotionApproveRequest,
    CanonicalParserPromotionRevokeRequest,
    CanonicalParserRuntimeBindRequest,
    CanonicalParserRuntimeUnbindRequest,
    CanonicalParserRuntimeAdmissionRequest,
    CanonicalParserRuntimeCertificationRequest,
    CanonicalParserRuntimeCertificationRevokeRequest,
    CanonicalParserShadowRuntimeLeaseIssueRequest,
    CanonicalParserShadowRuntimeLeaseRevokeRequest,
    CanonicalParserShadowConsumerRunRequest,
    CanonicalParserShadowReadinessAssessmentRequest,
    CanonicalQualityAssessmentRequest,
    CanonicalShadowValidationExecuteRequest,
    NormalizationReplayExecuteRequest,
    RawCaptureRetentionPruneRequest,
)
from backend.app.services.blockchain_canonical_quality_gate_service import (
    CanonicalQualityGateError,
    execute_canonical_quality_assessment,
    get_canonical_quality_assessment,
    get_canonical_quality_gate_status,
    preview_canonical_quality_gate,
)
from backend.app.services.blockchain_parser_promotion_service import (
    CanonicalParserPromotionError,
    approve_parser_promotion,
    get_parser_promotion,
    get_parser_promotion_status,
    preview_parser_promotion,
    revoke_parser_promotion,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    CanonicalParserRuntimeBindingError,
    bind_parser_runtime,
    get_parser_runtime_binding,
    get_parser_runtime_status,
    preview_parser_runtime_binding,
    resolve_shadow_parser_runtime,
    unbind_parser_runtime,
)
from backend.app.services.blockchain_parser_runtime_admission_service import (
    CanonicalParserRuntimeAdmissionError,
    get_parser_runtime_admission_run,
    get_parser_runtime_admission_status,
    preview_parser_runtime_admission,
    run_parser_runtime_admission,
)
from backend.app.services.blockchain_parser_runtime_certification_service import (
    CanonicalParserRuntimeCertificationError,
    certify_parser_runtime,
    get_parser_runtime_certification,
    get_parser_runtime_certification_status,
    preview_parser_runtime_certification,
    resolve_parser_runtime_certification,
    revoke_parser_runtime_certification,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    CanonicalParserShadowRuntimeLeaseError,
    get_shadow_runtime_lease,
    get_shadow_runtime_lease_status,
    issue_shadow_runtime_lease,
    preview_shadow_runtime_lease,
    resolve_shadow_runtime_lease,
    revoke_shadow_runtime_lease,
)
from backend.app.services.blockchain_parser_shadow_consumer_service import (
    CanonicalParserShadowConsumerError,
    get_shadow_consumer_run,
    get_shadow_consumer_status,
    preview_shadow_consumer_run,
    run_shadow_consumer_dry_run,
)
from backend.app.services.blockchain_parser_shadow_readiness_service import (
    CanonicalParserShadowReadinessError,
    execute_shadow_consumer_readiness_assessment,
    get_shadow_consumer_readiness_assessment,
    get_shadow_consumer_readiness_status,
    preview_shadow_consumer_readiness,
    resolve_shadow_consumer_readiness,
)
from backend.app.services.blockchain_canonical_shadow_service import (
    CanonicalShadowError,
    execute_canonical_materialization,
    execute_shadow_validation,
    get_canonical_shadow_status,
    get_shadow_validation_batch,
    preview_canonical_materialization,
    preview_shadow_validation,
)
from backend.app.services.blockchain_normalization_replay_service import (
    NormalizationReplayError,
    execute_normalization_replay,
    get_normalization_replay_batch,
    get_parser_registry_status,
    preview_normalization_replay,
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

# BEGIN M4 VERSIONED PARSER REGISTRY AND CONTROLLED REPLAY
@app.get(
    "/integrity/parsers",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_blockchain_parser_registry():
    return get_parser_registry_status()


@app.get(
    "/integrity/replay/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_normalization_replay_preview(
    parser_name: str = Query(min_length=3, max_length=80),
    parser_version: str = Query(min_length=5, max_length=64),
    selection_mode: str = Query(default="REPROCESS", max_length=16),
    provider: str | None = Query(default=None, min_length=1, max_length=64),
    event_type: str | None = Query(default=None, min_length=1, max_length=80),
    transaction_signature: str | None = Query(
        default=None,
        min_length=1,
        max_length=128,
    ),
    observed_wallet: str | None = Query(
        default=None,
        min_length=1,
        max_length=64,
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        return preview_normalization_replay(
            db,
            parser_name=parser_name,
            parser_version=parser_version,
            selection_mode=selection_mode,
            provider=provider,
            event_type=event_type,
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            limit=limit,
        )
    except NormalizationReplayError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception


@app.post(
    "/integrity/replay/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_controlled_normalization_replay(
    request: NormalizationReplayExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        observed_from = (
            datetime.fromisoformat(request.observed_from)
            if request.observed_from
            else None
        )
        observed_to = (
            datetime.fromisoformat(request.observed_to)
            if request.observed_to
            else None
        )
        return execute_normalization_replay(
            db,
            parser_name=request.parser_name,
            parser_version=request.parser_version,
            selection_mode=request.selection_mode,
            confirmation=request.confirmation,
            provider=request.provider,
            event_type=request.event_type,
            transaction_signature=request.transaction_signature,
            observed_wallet=request.observed_wallet,
            observed_from=observed_from,
            observed_to=observed_to,
            limit=request.limit,
        )
    except ValueError as exception:
        if isinstance(exception, NormalizationReplayError):
            raise HTTPException(
                status_code=exception.status_code,
                detail={
                    "code": exception.code,
                    "message": str(exception),
                },
            ) from exception
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REPLAY_DATETIME_INVALID",
                "message": "Intervallo temporale replay non valido.",
            },
        ) from exception


@app.get(
    "/integrity/replay/batches/{replay_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_normalization_replay_batch(
    replay_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_normalization_replay_batch(db, replay_id)
    except NormalizationReplayError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={
                "code": exception.code,
                "message": str(exception),
            },
        ) from exception
# END M4 VERSIONED PARSER REGISTRY AND CONTROLLED REPLAY

# BEGIN M5 CANONICAL NORMALIZATION AND SHADOW VALIDATION
@app.get(
    "/integrity/canonical/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_shadow_status(
    db: Session = Depends(get_db),
):
    return get_canonical_shadow_status(db)


@app.get(
    "/integrity/canonical/materialization/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_materialization_preview(
    provider: str | None = Query(default=None, min_length=1, max_length=64),
    observed_wallet: str | None = Query(
        default=None, min_length=1, max_length=64
    ),
    transaction_signature: str | None = Query(
        default=None, min_length=1, max_length=128
    ),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        return preview_canonical_materialization(
            db,
            provider=provider,
            observed_wallet=observed_wallet,
            transaction_signature=transaction_signature,
            limit=limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/canonical/materialization/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_canonical_materialization_endpoint(
    request: CanonicalMaterializationExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_canonical_materialization(
            db,
            confirmation=request.confirmation,
            provider=request.provider,
            observed_wallet=request.observed_wallet,
            transaction_signature=request.transaction_signature,
            limit=request.limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/shadow-validation/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_validation_preview(
    transaction_signature: str | None = Query(
        default=None, min_length=1, max_length=128
    ),
    observed_wallet: str | None = Query(
        default=None, min_length=1, max_length=64
    ),
    quality_status: str | None = Query(
        default=None, min_length=4, max_length=8
    ),
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_validation(
            db,
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            quality_status=quality_status,
            limit=limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/shadow-validation/execute",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_shadow_validation_endpoint(
    request: CanonicalShadowValidationExecuteRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_shadow_validation(
            db,
            confirmation=request.confirmation,
            transaction_signature=request.transaction_signature,
            observed_wallet=request.observed_wallet,
            quality_status=request.quality_status,
            limit=request.limit,
        )
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/shadow-validation/batches/{validation_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_validation_batch_endpoint(
    validation_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_validation_batch(db, validation_id)
    except CanonicalShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M5 CANONICAL NORMALIZATION AND SHADOW VALIDATION

# BEGIN M6 CANONICAL QUALITY GATE
@app.get(
    "/integrity/quality-gate/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_gate_status(
    db: Session = Depends(get_db),
):
    return get_canonical_quality_gate_status(db)


@app.get(
    "/integrity/quality-gate/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_gate_preview(
    validation_id: str | None = Query(
        default=None, min_length=36, max_length=36
    ),
    db: Session = Depends(get_db),
):
    try:
        return preview_canonical_quality_gate(
            db,
            validation_id=validation_id,
        )
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/quality-gate/assess",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def execute_canonical_quality_assessment_endpoint(
    request: CanonicalQualityAssessmentRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_canonical_quality_assessment(
            db,
            confirmation=request.confirmation,
            validation_id=request.validation_id,
        )
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/quality-gate/assessments/{assessment_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_canonical_quality_assessment_endpoint(
    assessment_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_canonical_quality_assessment(db, assessment_id)
    except CanonicalQualityGateError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M6 CANONICAL QUALITY GATE

# BEGIN M7 CANONICAL PARSER PROMOTION LEDGER
@app.get(
    "/integrity/parser-promotion/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_status(
    db: Session = Depends(get_db),
):
    return get_parser_promotion_status(db)


@app.get(
    "/integrity/parser-promotion/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_preview(
    assessment_id: str | None = Query(
        default=None, min_length=36, max_length=36
    ),
    scope: str = Query(default="SHADOW_ONLY", max_length=32),
    db: Session = Depends(get_db),
):
    try:
        return preview_parser_promotion(
            db,
            assessment_id=assessment_id,
            scope=scope,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-promotion/approve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def approve_parser_promotion_endpoint(
    request: CanonicalParserPromotionApproveRequest,
    db: Session = Depends(get_db),
):
    try:
        return approve_parser_promotion(
            db,
            confirmation=request.confirmation,
            assessment_id=request.assessment_id,
            scope=request.scope,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-promotion/revoke",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def revoke_parser_promotion_endpoint(
    request: CanonicalParserPromotionRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_parser_promotion(
            db,
            promotion_id=request.promotion_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-promotion/promotions/{promotion_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_promotion_endpoint(
    promotion_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_parser_promotion(db, promotion_id)
    except CanonicalParserPromotionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M7 CANONICAL PARSER PROMOTION LEDGER

# BEGIN M8 PARSER RUNTIME BINDING AND DRIFT CONTROL
@app.get(
    "/integrity/parser-runtime/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_status(db: Session = Depends(get_db)):
    return get_parser_runtime_status(db)


@app.get(
    "/integrity/parser-runtime/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_preview(
    promotion_id: str | None = Query(default=None, min_length=36, max_length=36),
    scope: str = Query(default="SHADOW_ONLY", max_length=32),
    channel: str = Query(default="CANONICAL_SHADOW", max_length=32),
    db: Session = Depends(get_db),
):
    try:
        return preview_parser_runtime_binding(
            db, promotion_id=promotion_id, scope=scope, channel=channel
        )
    except CanonicalParserRuntimeBindingError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-runtime/bind",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def bind_parser_runtime_endpoint(
    request: CanonicalParserRuntimeBindRequest,
    db: Session = Depends(get_db),
):
    try:
        return bind_parser_runtime(
            db,
            promotion_id=request.promotion_id,
            confirmation=request.confirmation,
            scope=request.scope,
            channel=request.channel,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserRuntimeBindingError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-runtime/unbind",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def unbind_parser_runtime_endpoint(
    request: CanonicalParserRuntimeUnbindRequest,
    db: Session = Depends(get_db),
):
    try:
        return unbind_parser_runtime(
            db,
            binding_id=request.binding_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserRuntimeBindingError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-runtime/bindings/{binding_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_binding_endpoint(
    binding_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_parser_runtime_binding(db, binding_id)
    except CanonicalParserRuntimeBindingError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-runtime/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_parser_runtime_endpoint(
    scope: str = Query(default="SHADOW_ONLY", max_length=32),
    channel: str = Query(default="CANONICAL_SHADOW", max_length=32),
    db: Session = Depends(get_db),
):
    try:
        return resolve_shadow_parser_runtime(db, scope=scope, channel=channel)
    except CanonicalParserRuntimeBindingError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M8 PARSER RUNTIME BINDING AND DRIFT CONTROL

# BEGIN M9 PARSER RUNTIME ADMISSION CANARY
@app.get(
    "/integrity/parser-admission/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_admission_status(db: Session = Depends(get_db)):
    return get_parser_runtime_admission_status(db)


@app.get(
    "/integrity/parser-admission/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_admission_preview(
    binding_id: str | None = Query(default=None, min_length=36, max_length=36),
    raw_event_ids: list[int] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return preview_parser_runtime_admission(
            db,
            binding_id=binding_id,
            raw_event_ids=raw_event_ids,
            limit=limit,
        )
    except CanonicalParserRuntimeAdmissionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-admission/run",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def run_parser_runtime_admission_endpoint(
    request: CanonicalParserRuntimeAdmissionRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_parser_runtime_admission(
            db,
            confirmation=request.confirmation,
            binding_id=request.binding_id,
            raw_event_ids=request.raw_event_ids,
            limit=request.limit,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserRuntimeAdmissionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-admission/runs/{admission_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_admission_run_endpoint(
    admission_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_parser_runtime_admission_run(db, admission_id)
    except CanonicalParserRuntimeAdmissionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M9 PARSER RUNTIME ADMISSION CANARY

# BEGIN M10 PARSER RUNTIME ADMISSION CERTIFICATION
@app.get(
    "/integrity/parser-certification/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_certification_status(db: Session = Depends(get_db)):
    return get_parser_runtime_certification_status(db)


@app.get(
    "/integrity/parser-certification/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_certification_preview(
    binding_id: str | None = Query(default=None, min_length=36, max_length=36),
    db: Session = Depends(get_db),
):
    try:
        return preview_parser_runtime_certification(db, binding_id=binding_id)
    except CanonicalParserRuntimeCertificationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-certification/certify",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def certify_parser_runtime_endpoint(
    request: CanonicalParserRuntimeCertificationRequest,
    db: Session = Depends(get_db),
):
    try:
        return certify_parser_runtime(
            db,
            confirmation=request.confirmation,
            binding_id=request.binding_id,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserRuntimeCertificationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-certification/revoke",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def revoke_parser_runtime_certification_endpoint(
    request: CanonicalParserRuntimeCertificationRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_parser_runtime_certification(
            db,
            certification_id=request.certification_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserRuntimeCertificationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-certification/certifications/{certification_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_parser_runtime_certification_endpoint(
    certification_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_parser_runtime_certification(db, certification_id)
    except CanonicalParserRuntimeCertificationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-certification/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_parser_runtime_certification_endpoint(db: Session = Depends(get_db)):
    return resolve_parser_runtime_certification(db)
# END M10 PARSER RUNTIME ADMISSION CERTIFICATION

# BEGIN M11 CERTIFIED SHADOW RUNTIME LEASE
@app.get(
    "/integrity/parser-shadow-lease/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_runtime_lease_status(db: Session = Depends(get_db)):
    return get_shadow_runtime_lease_status(db)


@app.get(
    "/integrity/parser-shadow-lease/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_runtime_lease_preview(
    certification_id: str | None = Query(default=None, min_length=36, max_length=36),
    validity_minutes: int = Query(default=30, ge=5, le=1440),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_runtime_lease(
            db,
            certification_id=certification_id,
            validity_minutes=validity_minutes,
        )
    except CanonicalParserShadowRuntimeLeaseError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-lease/issue",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def issue_shadow_runtime_lease_endpoint(
    request: CanonicalParserShadowRuntimeLeaseIssueRequest,
    db: Session = Depends(get_db),
):
    try:
        return issue_shadow_runtime_lease(
            db,
            confirmation=request.confirmation,
            certification_id=request.certification_id,
            validity_minutes=request.validity_minutes,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowRuntimeLeaseError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-lease/revoke",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def revoke_shadow_runtime_lease_endpoint(
    request: CanonicalParserShadowRuntimeLeaseRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_shadow_runtime_lease(
            db,
            lease_id=request.lease_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowRuntimeLeaseError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-lease/leases/{lease_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_runtime_lease_endpoint(
    lease_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_runtime_lease(db, lease_id)
    except CanonicalParserShadowRuntimeLeaseError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-lease/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_shadow_runtime_lease_endpoint(db: Session = Depends(get_db)):
    return resolve_shadow_runtime_lease(db)
# END M11 CERTIFIED SHADOW RUNTIME LEASE

# BEGIN M12 CERTIFIED SHADOW CONSUMER DRY-RUN
@app.get(
    "/integrity/parser-shadow-consumer/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_status(db: Session = Depends(get_db)):
    return get_shadow_consumer_status(db)


@app.get(
    "/integrity/parser-shadow-consumer/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_preview(
    lease_id: str | None = Query(default=None, min_length=36, max_length=36),
    raw_event_ids: list[int] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_consumer_run(
            db,
            lease_id=lease_id,
            raw_event_ids=raw_event_ids,
            limit=limit,
        )
    except CanonicalParserShadowConsumerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-consumer/run",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def run_shadow_consumer_endpoint(
    request: CanonicalParserShadowConsumerRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_shadow_consumer_dry_run(
            db,
            confirmation=request.confirmation,
            lease_id=request.lease_id,
            raw_event_ids=request.raw_event_ids,
            limit=request.limit,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowConsumerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-consumer/runs/{run_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_run_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_consumer_run(db, run_id)
    except CanonicalParserShadowConsumerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M12 CERTIFIED SHADOW CONSUMER DRY-RUN

# BEGIN M13 SHADOW CONSUMER READINESS ASSESSMENT
@app.get(
    "/integrity/parser-shadow-readiness/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_readiness_status(db: Session = Depends(get_db)):
    return get_shadow_consumer_readiness_status(db)


@app.get(
    "/integrity/parser-shadow-readiness/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_readiness_preview(
    lease_id: str | None = Query(default=None, min_length=36, max_length=36),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_consumer_readiness(db, lease_id=lease_id)
    except CanonicalParserShadowReadinessError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-readiness/assess",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def assess_shadow_consumer_readiness_endpoint(
    request: CanonicalParserShadowReadinessAssessmentRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_shadow_consumer_readiness_assessment(
            db,
            confirmation=request.confirmation,
            lease_id=request.lease_id,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowReadinessError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-readiness/assessments/{assessment_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_consumer_readiness_assessment_endpoint(
    assessment_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_consumer_readiness_assessment(db, assessment_id)
    except CanonicalParserShadowReadinessError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-readiness/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_shadow_consumer_readiness_endpoint(db: Session = Depends(get_db)):
    return resolve_shadow_consumer_readiness(db)
# END M13 SHADOW CONSUMER READINESS ASSESSMENT
