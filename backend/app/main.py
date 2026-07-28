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
    CanonicalParserShadowAutomationPermitIssueRequest,
    CanonicalParserShadowAutomationPermitRevokeRequest,
    CanonicalParserShadowExecutionTicketReserveRequest,
    CanonicalParserShadowExecutionTicketReleaseRequest,
    CanonicalParserShadowTicketExecutionRunRequest,
    CanonicalParserShadowAutomationCycleRunRequest,
    CanonicalParserShadowSchedulerStartRequest,
    CanonicalParserShadowSchedulerControlRequest,
    CanonicalParserShadowSchedulerHeartbeatRequest,
    CanonicalParserShadowSchedulerTickRequest,
    CanonicalParserShadowWorkerStartRequest,
    CanonicalParserShadowWorkerControlRequest,
    CanonicalParserShadowWorkerHeartbeatRequest,
    CanonicalParserShadowWorkerIterationRequest,
    CanonicalParserShadowWorkerLoopRunRequest,
    CanonicalParserShadowWorkerRecoveryRunRequest,
    CanonicalParserShadowReliabilityAssessmentRequest,
    CanonicalParserShadowReliabilityCertificationRequest,
    CanonicalParserShadowReliabilityCertificationRevokeRequest,
    CanonicalParserPaperProjectionRunRequest,
    CanonicalParserPaperProjectionReadinessAssessmentRequest,
    CanonicalParserPaperAdmissionCertificationRequest,
    CanonicalParserPaperAdmissionCertificationRevokeRequest,
    CanonicalParserPaperRuntimeBindRequest,
    CanonicalParserPaperRuntimeUnbindRequest,
    CanonicalParserPaperAdmissionCanaryRunRequest,
    CanonicalParserPaperCanaryReadinessAssessmentRequest,
    CanonicalParserPaperExecutionPermitIssueRequest,
    CanonicalParserPaperExecutionPermitRevokeRequest,
    CanonicalParserUnifiedDecisionRunRequest,
    CanonicalParserPermitBoundPaperExecutionRequest,
    CanonicalParserPermitBoundPaperReconcileRequest,
    CanonicalParserPaperCalibrationRunRequest,
    CanonicalParserPaperCampaignRunRequest,
    CanonicalParserPaperCampaignRecoveryRequest,
    CanonicalParserPaperOperationalAssessmentRequest,
    CanonicalParserMicroLiveCanaryPermitIssueRequest,
    CanonicalParserMicroLiveCanaryPermitRevokeRequest,
    CanonicalParserMicroLiveCanarySimulationRequest,
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
from backend.app.services.blockchain_parser_shadow_automation_permit_service import (
    CanonicalParserShadowAutomationPermitError,
    get_shadow_automation_permit,
    get_shadow_automation_permit_status,
    issue_shadow_automation_permit,
    preview_shadow_automation_permit,
    resolve_shadow_automation_permit,
    revoke_shadow_automation_permit,
)
from backend.app.services.blockchain_parser_shadow_execution_ticket_service import (
    CanonicalParserShadowExecutionTicketError,
    get_shadow_execution_ticket,
    get_shadow_execution_ticket_status,
    preview_shadow_execution_ticket,
    release_shadow_execution_ticket,
    reserve_shadow_execution_ticket,
    resolve_shadow_execution_ticket,
)
from backend.app.services.blockchain_parser_shadow_ticket_execution_service import (
    CanonicalParserShadowTicketExecutionError,
    get_shadow_ticket_execution_run,
    get_shadow_ticket_execution_status,
    preview_shadow_ticket_execution,
    run_shadow_ticket_execution,
)
from backend.app.services.blockchain_parser_shadow_automation_cycle_service import (
    CanonicalParserShadowAutomationCycleError,
    get_shadow_automation_cycle,
    get_shadow_automation_cycle_status,
    preview_shadow_automation_cycle,
    run_shadow_automation_cycle,
)
from backend.app.services.blockchain_parser_shadow_scheduler_service import (
    CanonicalParserShadowSchedulerError,
    engage_shadow_scheduler_kill_switch,
    get_shadow_scheduler_state,
    get_shadow_scheduler_status,
    get_shadow_scheduler_tick,
    heartbeat_shadow_scheduler,
    preview_shadow_scheduler_start,
    preview_shadow_scheduler_tick,
    reset_shadow_scheduler_kill_switch,
    run_shadow_scheduler_tick,
    start_shadow_scheduler,
    stop_shadow_scheduler,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    CanonicalParserShadowWorkerError,
    SHADOW_WORKER_HEARTBEAT_PREFIX,
    SHADOW_WORKER_KILL_PREFIX,
    SHADOW_WORKER_RESET_PREFIX,
    SHADOW_WORKER_STOP_PREFIX,
    control_shadow_worker,
    get_shadow_worker_iteration,
    get_shadow_worker_state,
    get_shadow_worker_status,
    heartbeat_shadow_worker,
    preview_shadow_worker_iteration,
    preview_shadow_worker_start,
    run_shadow_worker_iteration,
    start_shadow_worker,
)
from backend.app.services.blockchain_parser_shadow_worker_loop_service import (
    CanonicalParserShadowWorkerLoopError,
    get_shadow_worker_loop,
    get_shadow_worker_loop_status,
    preview_shadow_worker_loop,
    run_shadow_worker_loop,
)
from backend.app.services.blockchain_parser_shadow_worker_recovery_service import (
    CanonicalParserShadowWorkerRecoveryError,
    get_shadow_worker_recovery_run,
    get_shadow_worker_recovery_status,
    preview_shadow_worker_recovery,
    run_shadow_worker_recovery,
)
from backend.app.services.blockchain_parser_shadow_reliability_service import (
    CanonicalParserShadowReliabilityError,
    execute_shadow_reliability_assessment,
    get_shadow_reliability_assessment,
    get_shadow_reliability_status,
    preview_shadow_reliability_assessment,
    resolve_shadow_reliability,
)

from backend.app.services.blockchain_parser_shadow_reliability_certification_service import (
    CanonicalParserShadowReliabilityCertificationError,
    certify_shadow_reliability,
    get_shadow_reliability_certification,
    get_shadow_reliability_certification_status,
    preview_shadow_reliability_certification,
    resolve_shadow_reliability_certification,
    revoke_shadow_reliability_certification,
)
from backend.app.services.blockchain_parser_paper_projection_service import (
    CanonicalParserPaperProjectionError,
    get_paper_projection_run,
    get_paper_projection_status,
    preview_paper_projection,
    resolve_paper_projection,
    run_paper_projection,
)
from backend.app.services.blockchain_parser_paper_projection_readiness_service import (
    CanonicalParserPaperProjectionReadinessError,
    execute_paper_projection_readiness_assessment,
    get_paper_projection_readiness_assessment,
    get_paper_projection_readiness_status,
    preview_paper_projection_readiness,
    resolve_paper_projection_readiness,
)
from backend.app.services.blockchain_parser_paper_admission_certification_service import (
    CanonicalParserPaperAdmissionCertificationError,
    certify_paper_admission,
    get_paper_admission_certification,
    get_paper_admission_certification_status,
    preview_paper_admission_certification,
    resolve_paper_admission_certification,
    revoke_paper_admission_certification,
)
from backend.app.services.blockchain_parser_paper_runtime_binding_service import (
    CanonicalParserPaperRuntimeBindingError,
    bind_paper_runtime,
    get_paper_runtime_binding,
    get_paper_runtime_binding_status,
    preview_paper_runtime_binding,
    resolve_paper_runtime_binding,
    unbind_paper_runtime,
)
from backend.app.services.blockchain_parser_paper_admission_canary_service import (
    CanonicalParserPaperAdmissionCanaryError,
    get_paper_admission_canary_run,
    get_paper_admission_canary_status,
    preview_paper_admission_canary,
    resolve_paper_admission_canary,
    run_paper_admission_canary,
)
from backend.app.services.blockchain_parser_paper_canary_readiness_service import (
    CanonicalParserPaperCanaryReadinessError,
    execute_paper_canary_readiness_assessment,
    get_paper_canary_readiness_assessment,
    get_paper_canary_readiness_status,
    preview_paper_canary_readiness,
    resolve_paper_canary_readiness,
)
from backend.app.services.blockchain_parser_paper_execution_permit_service import (
    CanonicalParserPaperExecutionPermitError,
    get_paper_execution_permit,
    get_paper_execution_permit_status,
    issue_paper_execution_permit,
    preview_paper_execution_permit,
    resolve_paper_execution_permit,
    revoke_paper_execution_permit,
)
from backend.app.services.blockchain_parser_unified_decision_service import (
    CanonicalParserUnifiedDecisionError,
    get_unified_decision_run,
    get_unified_decision_status,
    preview_unified_decision,
    resolve_unified_decision,
    run_unified_decision_shadow_validation,
)
from backend.app.services.blockchain_parser_permit_bound_paper_execution_service import (
    CanonicalParserPermitBoundPaperExecutionError,
    execute_permit_bound_paper,
    get_permit_bound_paper_execution,
    get_permit_bound_paper_execution_status,
    preview_permit_bound_paper_execution,
    reconcile_permit_bound_paper_execution,
    resolve_permit_bound_paper_execution,
)
from backend.app.services.blockchain_parser_paper_calibration_service import (
    CanonicalParserPaperCalibrationError,
    get_paper_calibration_campaign,
    get_paper_calibration_status,
    preview_paper_calibration_campaign,
    resolve_paper_calibration_campaign,
    run_paper_calibration_campaign,
)
from backend.app.services.blockchain_parser_paper_campaign_orchestration_service import (
    CanonicalParserPaperCampaignError,
    assess_paper_operations,
    get_paper_campaign,
    get_paper_campaign_status,
    get_paper_operational_assessment,
    preview_paper_campaign,
    preview_paper_operational_assessment,
    recover_paper_campaign,
    resolve_paper_campaign,
    run_paper_campaign,
)
from backend.app.services.blockchain_parser_micro_live_canary_service import (
    CanonicalParserMicroLiveCanaryError,
    get_micro_live_canary_permit,
    get_micro_live_canary_simulation,
    get_micro_live_canary_status,
    issue_micro_live_canary_permit,
    preview_micro_live_canary_permit,
    preview_micro_live_canary_simulation,
    resolve_micro_live_canary,
    revoke_micro_live_canary_permit,
    simulate_micro_live_canary,
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

# BEGIN M14 CERTIFIED SHADOW AUTOMATION PERMIT
@app.get(
    "/integrity/parser-shadow-automation-permit/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_permit_status(db: Session = Depends(get_db)):
    return get_shadow_automation_permit_status(db)


@app.get(
    "/integrity/parser-shadow-automation-permit/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_permit_preview(
    assessment_id: str | None = Query(default=None, min_length=36, max_length=36),
    validity_minutes: int = Query(default=5, ge=1, le=1440),
    run_budget: int = Query(default=3, ge=1, le=1000),
    event_budget: int = Query(default=50, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_automation_permit(
            db,
            assessment_id=assessment_id,
            validity_minutes=validity_minutes,
            run_budget=run_budget,
            event_budget=event_budget,
        )
    except CanonicalParserShadowAutomationPermitError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-automation-permit/issue",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def issue_shadow_automation_permit_endpoint(
    request: CanonicalParserShadowAutomationPermitIssueRequest,
    db: Session = Depends(get_db),
):
    try:
        return issue_shadow_automation_permit(
            db,
            confirmation=request.confirmation,
            assessment_id=request.assessment_id,
            validity_minutes=request.validity_minutes,
            run_budget=request.run_budget,
            event_budget=request.event_budget,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowAutomationPermitError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-automation-permit/revoke",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def revoke_shadow_automation_permit_endpoint(
    request: CanonicalParserShadowAutomationPermitRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_shadow_automation_permit(
            db,
            permit_id=request.permit_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowAutomationPermitError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-automation-permit/permits/{permit_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_permit_endpoint(
    permit_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_automation_permit(db, permit_id)
    except CanonicalParserShadowAutomationPermitError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-automation-permit/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_shadow_automation_permit_endpoint(db: Session = Depends(get_db)):
    return resolve_shadow_automation_permit(db)
# END M14 CERTIFIED SHADOW AUTOMATION PERMIT

# BEGIN M15 SHADOW EXECUTION TICKET AND ATOMIC BUDGET RESERVATION
@app.get(
    "/integrity/parser-shadow-execution-ticket/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_execution_ticket_status(db: Session = Depends(get_db)):
    return get_shadow_execution_ticket_status(db)


@app.get(
    "/integrity/parser-shadow-execution-ticket/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_execution_ticket_preview(
    permit_id: str | None = Query(default=None, min_length=36, max_length=36),
    validity_seconds: int = Query(default=120, ge=1, le=3600),
    event_reservation: int = Query(default=10, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_execution_ticket(
            db,
            permit_id=permit_id,
            validity_seconds=validity_seconds,
            event_reservation=event_reservation,
        )
    except CanonicalParserShadowExecutionTicketError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-execution-ticket/reserve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def reserve_shadow_execution_ticket_endpoint(
    request: CanonicalParserShadowExecutionTicketReserveRequest,
    db: Session = Depends(get_db),
):
    try:
        return reserve_shadow_execution_ticket(
            db,
            confirmation=request.confirmation,
            permit_id=request.permit_id,
            validity_seconds=request.validity_seconds,
            event_reservation=request.event_reservation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowExecutionTicketError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-execution-ticket/release",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def release_shadow_execution_ticket_endpoint(
    request: CanonicalParserShadowExecutionTicketReleaseRequest,
    db: Session = Depends(get_db),
):
    try:
        return release_shadow_execution_ticket(
            db,
            ticket_id=request.ticket_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowExecutionTicketError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-execution-ticket/tickets/{ticket_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_execution_ticket_endpoint(
    ticket_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_execution_ticket(db, ticket_id)
    except CanonicalParserShadowExecutionTicketError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-execution-ticket/resolve",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def resolve_shadow_execution_ticket_endpoint(
    ticket_id: str | None = Query(default=None, min_length=36, max_length=36),
    db: Session = Depends(get_db),
):
    return resolve_shadow_execution_ticket(db, ticket_id=ticket_id)
# END M15 SHADOW EXECUTION TICKET AND ATOMIC BUDGET RESERVATION

# BEGIN M16 TICKET-BOUND SHADOW EXECUTION AND ATOMIC BUDGET SETTLEMENT
@app.get(
    "/integrity/parser-shadow-ticket-execution/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_ticket_execution_status(db: Session = Depends(get_db)):
    return get_shadow_ticket_execution_status(db)


@app.get(
    "/integrity/parser-shadow-ticket-execution/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_ticket_execution_preview(
    ticket_id: str | None = Query(default=None, min_length=36, max_length=36),
    raw_event_ids: list[int] | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_ticket_execution(
            db,
            ticket_id=ticket_id,
            raw_event_ids=raw_event_ids,
            limit=limit,
        )
    except CanonicalParserShadowTicketExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-ticket-execution/run",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def run_shadow_ticket_execution_endpoint(
    request: CanonicalParserShadowTicketExecutionRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_shadow_ticket_execution(
            db,
            confirmation=request.confirmation,
            ticket_id=request.ticket_id,
            raw_event_ids=request.raw_event_ids,
            limit=request.limit,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowTicketExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-ticket-execution/runs/{run_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_ticket_execution_run_endpoint(
    run_id: str,
    db: Session = Depends(get_db),
):
    try:
        return get_shadow_ticket_execution_run(db, run_id)
    except CanonicalParserShadowTicketExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M16 TICKET-BOUND SHADOW EXECUTION AND ATOMIC BUDGET SETTLEMENT


# BEGIN M17 SHADOW AUTOMATION CYCLE COORDINATOR
@app.get(
    "/integrity/parser-shadow-automation-cycle/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_cycle_status(db: Session = Depends(get_db)):
    return get_shadow_automation_cycle_status(db)


@app.get(
    "/integrity/parser-shadow-automation-cycle/preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_cycle_preview(
    permit_id: str | None = Query(default=None, min_length=36, max_length=36),
    raw_event_ids: list[int] | None = Query(default=None),
    event_reservation: int = Query(default=10, ge=1, le=100),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_automation_cycle(
            db,
            permit_id=permit_id,
            raw_event_ids=raw_event_ids,
            event_reservation=event_reservation,
            limit=limit,
        )
    except CanonicalParserShadowAutomationCycleError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-automation-cycle/run",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def run_shadow_automation_cycle_endpoint(
    request: CanonicalParserShadowAutomationCycleRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_shadow_automation_cycle(
            db,
            confirmation=request.confirmation,
            permit_id=request.permit_id,
            raw_event_ids=request.raw_event_ids,
            event_reservation=request.event_reservation,
            limit=request.limit,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowAutomationCycleError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-automation-cycle/cycles/{cycle_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_automation_cycle_endpoint(
    cycle_id: str, db: Session = Depends(get_db)
):
    try:
        return get_shadow_automation_cycle(db, cycle_id)
    except CanonicalParserShadowAutomationCycleError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M17 SHADOW AUTOMATION CYCLE COORDINATOR


# BEGIN M18 SHADOW SCHEDULER CONTROL PLANE
@app.get(
    "/integrity/parser-shadow-scheduler/status",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_scheduler_status(db: Session = Depends(get_db)):
    return get_shadow_scheduler_status(db)


@app.get(
    "/integrity/parser-shadow-scheduler/state",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_scheduler_state(db: Session = Depends(get_db)):
    return get_shadow_scheduler_state(db)


@app.get(
    "/integrity/parser-shadow-scheduler/start-preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_scheduler_start_preview(
    permit_id: str = Query(min_length=36, max_length=36),
    interval_seconds: int = Query(default=300, ge=1, le=86400),
    event_reservation: int = Query(default=10, ge=1, le=100),
    limit: int = Query(default=10, ge=1, le=100),
):
    return preview_shadow_scheduler_start(
        permit_id=permit_id,
        interval_seconds=interval_seconds,
        event_reservation=event_reservation,
        limit=limit,
    )


@app.post(
    "/integrity/parser-shadow-scheduler/start",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def start_shadow_scheduler_endpoint(
    request: CanonicalParserShadowSchedulerStartRequest,
    db: Session = Depends(get_db),
):
    try:
        return start_shadow_scheduler(
            db,
            confirmation=request.confirmation,
            permit_id=request.permit_id,
            interval_seconds=request.interval_seconds,
            event_reservation=request.event_reservation,
            limit=request.limit,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-scheduler/stop",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def stop_shadow_scheduler_endpoint(
    request: CanonicalParserShadowSchedulerControlRequest,
    db: Session = Depends(get_db),
):
    try:
        return stop_shadow_scheduler(
            db,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-scheduler/kill",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def kill_shadow_scheduler_endpoint(
    request: CanonicalParserShadowSchedulerControlRequest,
    db: Session = Depends(get_db),
):
    try:
        return engage_shadow_scheduler_kill_switch(
            db,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-scheduler/reset",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def reset_shadow_scheduler_endpoint(
    request: CanonicalParserShadowSchedulerControlRequest,
    db: Session = Depends(get_db),
):
    try:
        return reset_shadow_scheduler_kill_switch(
            db,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-scheduler/heartbeat",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def heartbeat_shadow_scheduler_endpoint(
    request: CanonicalParserShadowSchedulerHeartbeatRequest,
    db: Session = Depends(get_db),
):
    try:
        return heartbeat_shadow_scheduler(
            db,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-scheduler/tick-preview",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_scheduler_tick_preview(
    raw_event_ids: list[int] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return preview_shadow_scheduler_tick(db, raw_event_ids=raw_event_ids)
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post(
    "/integrity/parser-shadow-scheduler/tick",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def run_shadow_scheduler_tick_endpoint(
    request: CanonicalParserShadowSchedulerTickRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_shadow_scheduler_tick(
            db,
            confirmation=request.confirmation,
            raw_event_ids=request.raw_event_ids,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get(
    "/integrity/parser-shadow-scheduler/ticks/{tick_id}",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)
def read_shadow_scheduler_tick_endpoint(
    tick_id: str, db: Session = Depends(get_db)
):
    try:
        return get_shadow_scheduler_tick(db, tick_id)
    except CanonicalParserShadowSchedulerError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception
# END M18 SHADOW SCHEDULER CONTROL PLANE


# BEGIN M19 SHADOW SCHEDULER WORKER RUNTIME
@app.get("/integrity/parser-shadow-worker/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_status(db: Session = Depends(get_db)):
    return get_shadow_worker_status(db)

@app.get("/integrity/parser-shadow-worker/state", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_state(db: Session = Depends(get_db)):
    return get_shadow_worker_state(db)

@app.get("/integrity/parser-shadow-worker/start-preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_start_preview(owner_id: str = Query(min_length=3, max_length=80)):
    return preview_shadow_worker_start(owner_id=owner_id)

@app.post("/integrity/parser-shadow-worker/start", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def start_shadow_worker_endpoint(request: CanonicalParserShadowWorkerStartRequest, db: Session = Depends(get_db)):
    try:
        return start_shadow_worker(db, confirmation=request.confirmation, owner_id=request.owner_id, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker/stop", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def stop_shadow_worker_endpoint(request: CanonicalParserShadowWorkerControlRequest, db: Session = Depends(get_db)):
    try:
        return control_shadow_worker(db, action="STOP", confirmation=request.confirmation, owner_id=request.owner_id, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker/kill", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def kill_shadow_worker_endpoint(request: CanonicalParserShadowWorkerControlRequest, db: Session = Depends(get_db)):
    try:
        return control_shadow_worker(db, action="KILL", confirmation=request.confirmation, owner_id=request.owner_id, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker/reset", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def reset_shadow_worker_endpoint(request: CanonicalParserShadowWorkerControlRequest, db: Session = Depends(get_db)):
    try:
        return control_shadow_worker(db, action="RESET", confirmation=request.confirmation, owner_id=request.owner_id, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker/heartbeat", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def heartbeat_shadow_worker_endpoint(request: CanonicalParserShadowWorkerHeartbeatRequest, db: Session = Depends(get_db)):
    try:
        return heartbeat_shadow_worker(db, confirmation=request.confirmation, owner_id=request.owner_id, actor_label=request.actor_label)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-worker/iteration-preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_iteration_preview(owner_id: str = Query(min_length=3, max_length=80), raw_event_ids: list[int] | None = Query(default=None), db: Session = Depends(get_db)):
    try:
        return preview_shadow_worker_iteration(db, owner_id=owner_id, raw_event_ids=raw_event_ids)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker/iterate", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_shadow_worker_iteration_endpoint(request: CanonicalParserShadowWorkerIterationRequest, db: Session = Depends(get_db)):
    try:
        return run_shadow_worker_iteration(db, confirmation=request.confirmation, owner_id=request.owner_id, raw_event_ids=request.raw_event_ids, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-worker/iterations/{iteration_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_iteration_endpoint(iteration_id: str, db: Session = Depends(get_db)):
    try:
        return get_shadow_worker_iteration(db, iteration_id)
    except CanonicalParserShadowWorkerError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception
# END M19 SHADOW SCHEDULER WORKER RUNTIME

# BEGIN M20 BOUNDED SHADOW WORKER LOOP
@app.get("/integrity/parser-shadow-worker-loop/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_loop_status(db: Session = Depends(get_db)):
    return get_shadow_worker_loop_status(db)

@app.get("/integrity/parser-shadow-worker-loop/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_loop_preview(owner_id: str = Query(min_length=3, max_length=80), iterations: int = Query(default=3, ge=1, le=50), raw_event_ids: list[int] | None = Query(default=None), db: Session = Depends(get_db)):
    try:
        return preview_shadow_worker_loop(db, owner_id=owner_id, iterations=iterations, raw_event_ids=raw_event_ids)
    except CanonicalParserShadowWorkerLoopError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-worker-loop/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_shadow_worker_loop_endpoint(request: CanonicalParserShadowWorkerLoopRunRequest, db: Session = Depends(get_db)):
    try:
        return run_shadow_worker_loop(db, confirmation=request.confirmation, owner_id=request.owner_id, iterations=request.iterations, raw_event_ids=request.raw_event_ids, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowWorkerLoopError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-worker-loop/runs/{loop_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_loop_endpoint(loop_id: str, db: Session = Depends(get_db)):
    try:
        return get_shadow_worker_loop(db, loop_id)
    except CanonicalParserShadowWorkerLoopError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception
# END M20 BOUNDED SHADOW WORKER LOOP

# BEGIN M21 SHADOW WORKER RECOVERY
@app.get("/integrity/parser-shadow-worker-recovery/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_recovery_status(db: Session = Depends(get_db)):
    return get_shadow_worker_recovery_status(db)

@app.get("/integrity/parser-shadow-worker-recovery/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_recovery_preview(db: Session = Depends(get_db)):
    return preview_shadow_worker_recovery(db)

@app.post("/integrity/parser-shadow-worker-recovery/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_shadow_worker_recovery_endpoint(request: CanonicalParserShadowWorkerRecoveryRunRequest, db: Session = Depends(get_db)):
    try:
        return run_shadow_worker_recovery(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowWorkerRecoveryError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-worker-recovery/runs/{recovery_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_worker_recovery_run_endpoint(recovery_id: str, db: Session = Depends(get_db)):
    try:
        return get_shadow_worker_recovery_run(db, recovery_id)
    except CanonicalParserShadowWorkerRecoveryError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception
# END M21 SHADOW WORKER RECOVERY

# BEGIN M22 SHADOW RELIABILITY EVIDENCE GATE
@app.get("/integrity/parser-shadow-reliability/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_status(db: Session = Depends(get_db)):
    return get_shadow_reliability_status(db)

@app.get("/integrity/parser-shadow-reliability/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_preview(db: Session = Depends(get_db)):
    return preview_shadow_reliability_assessment(db)

@app.post("/integrity/parser-shadow-reliability/assess", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def assess_shadow_reliability_endpoint(request: CanonicalParserShadowReliabilityAssessmentRequest, db: Session = Depends(get_db)):
    try:
        return execute_shadow_reliability_assessment(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowReliabilityError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-reliability/assessments/{assessment_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_assessment_endpoint(assessment_id: str, db: Session = Depends(get_db)):
    try:
        return get_shadow_reliability_assessment(db, assessment_id)
    except CanonicalParserShadowReliabilityError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-reliability/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_shadow_reliability_endpoint(db: Session = Depends(get_db)):
    return resolve_shadow_reliability(db)
# END M22 SHADOW RELIABILITY EVIDENCE GATE

# BEGIN M23 SHADOW RELIABILITY CERTIFICATION
@app.get("/integrity/parser-shadow-reliability-certification/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_certification_status(db: Session = Depends(get_db)):
    return get_shadow_reliability_certification_status(db)

@app.get("/integrity/parser-shadow-reliability-certification/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_certification_preview(db: Session = Depends(get_db)):
    return preview_shadow_reliability_certification(db)

@app.post("/integrity/parser-shadow-reliability-certification/certify", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def certify_shadow_reliability_endpoint(request: CanonicalParserShadowReliabilityCertificationRequest, db: Session = Depends(get_db)):
    try:
        return certify_shadow_reliability(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserShadowReliabilityCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-shadow-reliability-certification/revoke", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def revoke_shadow_reliability_certification_endpoint(request: CanonicalParserShadowReliabilityCertificationRevokeRequest, db: Session = Depends(get_db)):
    try:
        return revoke_shadow_reliability_certification(db, certification_id=request.certification_id, confirmation=request.confirmation, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserShadowReliabilityCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-reliability-certification/certifications/{certification_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_shadow_reliability_certification_endpoint(certification_id: str, db: Session = Depends(get_db)):
    try:
        return get_shadow_reliability_certification(db, certification_id)
    except CanonicalParserShadowReliabilityCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-shadow-reliability-certification/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_shadow_reliability_certification_endpoint(db: Session = Depends(get_db)):
    return resolve_shadow_reliability_certification(db)
# END M23 SHADOW RELIABILITY CERTIFICATION

# BEGIN M24 PAPER PROJECTION DRY RUN
@app.get("/integrity/parser-paper-projection/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_status(db: Session = Depends(get_db)):
    return get_paper_projection_status(db)

@app.get("/integrity/parser-paper-projection/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_preview(db: Session = Depends(get_db)):
    return preview_paper_projection(db)

@app.post("/integrity/parser-paper-projection/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_paper_projection_endpoint(request: CanonicalParserPaperProjectionRunRequest, db: Session = Depends(get_db)):
    try:
        return run_paper_projection(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserPaperProjectionError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-projection/runs/{projection_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_run_endpoint(projection_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_projection_run(db, projection_id)
    except CanonicalParserPaperProjectionError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-projection/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_projection_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_projection(db)
# END M24 PAPER PROJECTION DRY RUN

# BEGIN M25 PAPER PROJECTION READINESS EVIDENCE GATE
@app.get("/integrity/parser-paper-projection-readiness/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_readiness_status(db: Session = Depends(get_db)):
    return get_paper_projection_readiness_status(db)

@app.get("/integrity/parser-paper-projection-readiness/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_readiness_preview(db: Session = Depends(get_db)):
    return preview_paper_projection_readiness(db)

@app.post("/integrity/parser-paper-projection-readiness/assess", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def assess_paper_projection_readiness_endpoint(request: CanonicalParserPaperProjectionReadinessAssessmentRequest, db: Session = Depends(get_db)):
    try:
        return execute_paper_projection_readiness_assessment(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserPaperProjectionReadinessError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-projection-readiness/assessments/{assessment_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_projection_readiness_assessment_endpoint(assessment_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_projection_readiness_assessment(db, assessment_id)
    except CanonicalParserPaperProjectionReadinessError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-projection-readiness/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_projection_readiness_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_projection_readiness(db)
# END M25 PAPER PROJECTION READINESS EVIDENCE GATE

# BEGIN M26 PAPER ADMISSION CERTIFICATION
@app.get("/integrity/parser-paper-admission-certification/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_certification_status(db: Session = Depends(get_db)):
    return get_paper_admission_certification_status(db)

@app.get("/integrity/parser-paper-admission-certification/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_certification_preview(db: Session = Depends(get_db)):
    return preview_paper_admission_certification(db)

@app.post("/integrity/parser-paper-admission-certification/certify", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def certify_paper_admission_endpoint(request: CanonicalParserPaperAdmissionCertificationRequest, db: Session = Depends(get_db)):
    try:
        return certify_paper_admission(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserPaperAdmissionCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-paper-admission-certification/revoke", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def revoke_paper_admission_certification_endpoint(request: CanonicalParserPaperAdmissionCertificationRevokeRequest, db: Session = Depends(get_db)):
    try:
        return revoke_paper_admission_certification(db, certification_id=request.certification_id, confirmation=request.confirmation, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserPaperAdmissionCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-admission-certification/certifications/{certification_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_certification_endpoint(certification_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_admission_certification(db, certification_id)
    except CanonicalParserPaperAdmissionCertificationError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-admission-certification/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_admission_certification_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_admission_certification(db)
# END M26 PAPER ADMISSION CERTIFICATION

# BEGIN M27 PAPER RUNTIME BINDING
@app.get("/integrity/parser-paper-runtime-binding/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_runtime_binding_status(db: Session = Depends(get_db)):
    return get_paper_runtime_binding_status(db)

@app.get("/integrity/parser-paper-runtime-binding/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_runtime_binding_preview(paper_account_id: int = Query(..., ge=1), db: Session = Depends(get_db)):
    return preview_paper_runtime_binding(db, paper_account_id=paper_account_id)

@app.post("/integrity/parser-paper-runtime-binding/bind", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def bind_paper_runtime_endpoint(request: CanonicalParserPaperRuntimeBindRequest, db: Session = Depends(get_db)):
    try:
        return bind_paper_runtime(db, paper_account_id=request.paper_account_id, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserPaperRuntimeBindingError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.post("/integrity/parser-paper-runtime-binding/unbind", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def unbind_paper_runtime_endpoint(request: CanonicalParserPaperRuntimeUnbindRequest, db: Session = Depends(get_db)):
    try:
        return unbind_paper_runtime(db, binding_id=request.binding_id, confirmation=request.confirmation, reason=request.reason, actor_label=request.actor_label)
    except CanonicalParserPaperRuntimeBindingError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-runtime-binding/bindings/{binding_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_runtime_binding_endpoint(binding_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_runtime_binding(db, binding_id)
    except CanonicalParserPaperRuntimeBindingError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-runtime-binding/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_runtime_binding_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_runtime_binding(db)
# END M27 PAPER RUNTIME BINDING

# BEGIN M28 PAPER ADMISSION CANARY
@app.get("/integrity/parser-paper-admission-canary/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_canary_status(db: Session = Depends(get_db)):
    return get_paper_admission_canary_status(db)

@app.get("/integrity/parser-paper-admission-canary/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_canary_preview(db: Session = Depends(get_db)):
    return preview_paper_admission_canary(db)

@app.post("/integrity/parser-paper-admission-canary/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_paper_admission_canary_endpoint(request: CanonicalParserPaperAdmissionCanaryRunRequest, db: Session = Depends(get_db)):
    try:
        return run_paper_admission_canary(db, confirmation=request.confirmation, actor_label=request.actor_label, note=request.note)
    except CanonicalParserPaperAdmissionCanaryError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-admission-canary/runs/{canary_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_admission_canary_run_endpoint(canary_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_admission_canary_run(db, canary_id)
    except CanonicalParserPaperAdmissionCanaryError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception

@app.get("/integrity/parser-paper-admission-canary/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_admission_canary_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_admission_canary(db)
# END M28 PAPER ADMISSION CANARY

# BEGIN M29 PAPER CANARY READINESS EVIDENCE GATE
@app.get("/integrity/parser-paper-canary-readiness/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_canary_readiness_status(db: Session = Depends(get_db)):
    return get_paper_canary_readiness_status(db)


@app.get("/integrity/parser-paper-canary-readiness/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_canary_readiness_preview(db: Session = Depends(get_db)):
    return preview_paper_canary_readiness(db)


@app.post("/integrity/parser-paper-canary-readiness/assess", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def assess_paper_canary_readiness_endpoint(request: CanonicalParserPaperCanaryReadinessAssessmentRequest, db: Session = Depends(get_db)):
    try:
        return execute_paper_canary_readiness_assessment(
            db,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPaperCanaryReadinessError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception


@app.get("/integrity/parser-paper-canary-readiness/assessments/{assessment_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_canary_readiness_assessment_endpoint(assessment_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_canary_readiness_assessment(db, assessment_id)
    except CanonicalParserPaperCanaryReadinessError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception


@app.get("/integrity/parser-paper-canary-readiness/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_canary_readiness_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_canary_readiness(db)
# END M29 PAPER CANARY READINESS EVIDENCE GATE

# BEGIN M30 PAPER EXECUTION PERMIT GOVERNANCE
@app.get("/integrity/parser-paper-execution-permit/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_execution_permit_status(db: Session = Depends(get_db)):
    return get_paper_execution_permit_status(db)


@app.get("/integrity/parser-paper-execution-permit/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_execution_permit_preview(
    readiness_assessment_id: str | None = Query(default=None, min_length=36, max_length=36),
    validity_minutes: int = Query(default=15, ge=1, le=1440),
    total_budget_sol: float = Query(default=0.5, gt=0, le=1000000),
    max_order_budget_sol: float = Query(default=0.1, gt=0, le=1000000),
    max_order_count: int = Query(default=5, ge=1, le=100000),
    db: Session = Depends(get_db),
):
    return preview_paper_execution_permit(
        db,
        readiness_assessment_id=readiness_assessment_id,
        validity_minutes=validity_minutes,
        total_budget_sol=total_budget_sol,
        max_order_budget_sol=max_order_budget_sol,
        max_order_count=max_order_count,
    )


@app.post("/integrity/parser-paper-execution-permit/issue", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def issue_paper_execution_permit_endpoint(request: CanonicalParserPaperExecutionPermitIssueRequest, db: Session = Depends(get_db)):
    try:
        return issue_paper_execution_permit(
            db,
            readiness_assessment_id=request.readiness_assessment_id,
            validity_minutes=request.validity_minutes,
            total_budget_sol=request.total_budget_sol,
            max_order_budget_sol=request.max_order_budget_sol,
            max_order_count=request.max_order_count,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPaperExecutionPermitError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception


@app.post("/integrity/parser-paper-execution-permit/revoke", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def revoke_paper_execution_permit_endpoint(request: CanonicalParserPaperExecutionPermitRevokeRequest, db: Session = Depends(get_db)):
    try:
        return revoke_paper_execution_permit(
            db,
            permit_id=request.permit_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserPaperExecutionPermitError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception


@app.get("/integrity/parser-paper-execution-permit/permits/{permit_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_execution_permit_endpoint(permit_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_execution_permit(db, permit_id)
    except CanonicalParserPaperExecutionPermitError as exception:
        raise HTTPException(status_code=exception.status_code, detail={"code": exception.code, "message": str(exception)}) from exception


@app.get("/integrity/parser-paper-execution-permit/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_execution_permit_endpoint(db: Session = Depends(get_db)):
    return resolve_paper_execution_permit(db)
# END M30 PAPER EXECUTION PERMIT GOVERNANCE

# BEGIN M31 UNIFIED DECISION INTELLIGENCE & SHADOW VALIDATION
@app.get("/integrity/parser-unified-decision/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_unified_decision_status(db: Session = Depends(get_db)):
    return get_unified_decision_status(db)


@app.get("/integrity/parser-unified-decision/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_unified_decision_preview(
    lookback_minutes: int | None = Query(default=None, ge=1, le=10080),
    max_results: int | None = Query(default=None, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return preview_unified_decision(
        db,
        lookback_minutes=lookback_minutes,
        max_results=max_results,
    )


@app.post("/integrity/parser-unified-decision/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_unified_decision_endpoint(
    request: CanonicalParserUnifiedDecisionRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_unified_decision_shadow_validation(
            db,
            confirmation=request.confirmation,
            lookback_minutes=request.lookback_minutes,
            max_results=request.max_results,
            source_trade_ids=request.source_trade_ids,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserUnifiedDecisionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-unified-decision/runs/{run_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_unified_decision_run_endpoint(run_id: str, db: Session = Depends(get_db)):
    try:
        return get_unified_decision_run(db, run_id)
    except CanonicalParserUnifiedDecisionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-unified-decision/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_unified_decision_endpoint(
    token_mint: str | None = Query(default=None, min_length=32, max_length=64),
    db: Session = Depends(get_db),
):
    return resolve_unified_decision(db, token_mint=token_mint)
# END M31 UNIFIED DECISION INTELLIGENCE & SHADOW VALIDATION

# BEGIN M32 PERMIT-BOUND PAPER EXECUTION
@app.get("/integrity/parser-permit-bound-paper-execution/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_permit_bound_paper_execution_status(db: Session = Depends(get_db)):
    return get_permit_bound_paper_execution_status(db)


@app.get("/integrity/parser-permit-bound-paper-execution/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_permit_bound_paper_execution_preview(
    permit_id: str = Query(min_length=36, max_length=36),
    decision_result_id: str = Query(min_length=36, max_length=36),
    side: str = Query(pattern="^(BUY|SELL)$"),
    market_price_sol: float = Query(gt=0, le=1000000000),
    idempotency_token: str = Query(min_length=8, max_length=200),
    quantity: float | None = Query(default=None, gt=0),
    slippage_percent: float = Query(default=0.5, ge=0, le=50),
    fee_percent: float = Query(default=0.25, ge=0, le=20),
    db: Session = Depends(get_db),
):
    try:
        return preview_permit_bound_paper_execution(
            db,
            permit_id=permit_id,
            decision_result_id=decision_result_id,
            side=side,
            market_price_sol=market_price_sol,
            idempotency_token=idempotency_token,
            quantity=quantity,
            slippage_percent=slippage_percent,
            fee_percent=fee_percent,
        )
    except CanonicalParserPermitBoundPaperExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-permit-bound-paper-execution/execute", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def execute_permit_bound_paper_endpoint(
    request: CanonicalParserPermitBoundPaperExecutionRequest,
    db: Session = Depends(get_db),
):
    try:
        return execute_permit_bound_paper(
            db,
            permit_id=request.permit_id,
            decision_result_id=request.decision_result_id,
            side=request.side,
            market_price_sol=request.market_price_sol,
            idempotency_token=request.idempotency_token,
            confirmation=request.confirmation,
            quantity=request.quantity,
            slippage_percent=request.slippage_percent,
            fee_percent=request.fee_percent,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPermitBoundPaperExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-permit-bound-paper-execution/reconcile", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def reconcile_permit_bound_paper_endpoint(
    request: CanonicalParserPermitBoundPaperReconcileRequest,
    db: Session = Depends(get_db),
):
    try:
        return reconcile_permit_bound_paper_execution(
            db,
            execution_id=request.execution_id,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
        )
    except CanonicalParserPermitBoundPaperExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-permit-bound-paper-execution/executions/{execution_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_permit_bound_paper_execution_endpoint(execution_id: str, db: Session = Depends(get_db)):
    try:
        return get_permit_bound_paper_execution(db, execution_id)
    except CanonicalParserPermitBoundPaperExecutionError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-permit-bound-paper-execution/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_permit_bound_paper_execution_endpoint(
    paper_account_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return resolve_permit_bound_paper_execution(db, paper_account_id=paper_account_id)
# END M32 PERMIT-BOUND PAPER EXECUTION


# BEGIN M33 PAPER RELIABILITY & CALIBRATION CAMPAIGN
@app.get("/integrity/parser-paper-calibration/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_calibration_status(db: Session = Depends(get_db)):
    return get_paper_calibration_status(db)


@app.get("/integrity/parser-paper-calibration/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_calibration_preview(
    paper_account_id: int = Query(ge=1),
    permit_id: str | None = Query(default=None, min_length=36, max_length=36),
    lookback_days: int | None = Query(default=None, ge=1, le=3650),
    db: Session = Depends(get_db),
):
    try:
        return preview_paper_calibration_campaign(
            db,
            paper_account_id=paper_account_id,
            permit_id=permit_id,
            lookback_days=lookback_days,
        )
    except CanonicalParserPaperCalibrationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-paper-calibration/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_paper_calibration_endpoint(
    request: CanonicalParserPaperCalibrationRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_paper_calibration_campaign(
            db,
            paper_account_id=request.paper_account_id,
            permit_id=request.permit_id,
            lookback_days=request.lookback_days,
            window_started_at=request.window_started_at,
            window_ended_at=request.window_ended_at,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPaperCalibrationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-calibration/campaigns/{campaign_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_calibration_campaign_endpoint(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_calibration_campaign(db, campaign_id)
    except CanonicalParserPaperCalibrationError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-calibration/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_calibration_endpoint(
    paper_account_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return resolve_paper_calibration_campaign(db, paper_account_id=paper_account_id)
# END M33 PAPER RELIABILITY & CALIBRATION CAMPAIGN

# BEGIN M34 PAPER CAMPAIGN ORCHESTRATION & OPERATIONAL HARDENING
@app.get("/integrity/parser-paper-campaign/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_campaign_status(db: Session = Depends(get_db)):
    return get_paper_campaign_status(db)


@app.post("/integrity/parser-paper-campaign/preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def preview_paper_campaign_endpoint(
    request: CanonicalParserPaperCampaignRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return preview_paper_campaign(
            db,
            permit_id=request.permit_id,
            items=[item.model_dump() for item in request.items],
        )
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-paper-campaign/run", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def run_paper_campaign_endpoint(
    request: CanonicalParserPaperCampaignRunRequest,
    db: Session = Depends(get_db),
):
    try:
        return run_paper_campaign(
            db,
            permit_id=request.permit_id,
            items=[item.model_dump() for item in request.items],
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-paper-campaign/recover", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def recover_paper_campaign_endpoint(
    request: CanonicalParserPaperCampaignRecoveryRequest,
    db: Session = Depends(get_db),
):
    try:
        return recover_paper_campaign(
            db,
            campaign_id=request.campaign_id,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
        )
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-campaign/campaigns/{campaign_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_campaign_endpoint(campaign_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_campaign(db, campaign_id)
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-campaign/operational-preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def preview_paper_operational_endpoint(
    paper_account_id: int = Query(ge=1),
    calibration_campaign_id: str | None = Query(default=None, min_length=36, max_length=36),
    db: Session = Depends(get_db),
):
    try:
        return preview_paper_operational_assessment(
            db,
            paper_account_id=paper_account_id,
            calibration_campaign_id=calibration_campaign_id,
        )
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-paper-campaign/operational-assess", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def assess_paper_operations_endpoint(
    request: CanonicalParserPaperOperationalAssessmentRequest,
    db: Session = Depends(get_db),
):
    try:
        return assess_paper_operations(
            db,
            paper_account_id=request.paper_account_id,
            calibration_campaign_id=request.calibration_campaign_id,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-campaign/assessments/{assessment_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_paper_operational_assessment_endpoint(assessment_id: str, db: Session = Depends(get_db)):
    try:
        return get_paper_operational_assessment(db, assessment_id)
    except CanonicalParserPaperCampaignError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-paper-campaign/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_paper_campaign_endpoint(
    paper_account_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
):
    return resolve_paper_campaign(db, paper_account_id=paper_account_id)
# END M34 PAPER CAMPAIGN ORCHESTRATION & OPERATIONAL HARDENING


# BEGIN M35 MICRO-LIVE CANARY GOVERNANCE & SIMULATION
@app.get("/integrity/parser-micro-live-canary/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_micro_live_canary_status(db: Session = Depends(get_db)):
    return get_micro_live_canary_status(db)


@app.get("/integrity/parser-micro-live-canary/permit-preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def preview_micro_live_canary_permit_endpoint(
    operational_assessment_id: str = Query(min_length=36, max_length=36),
    validity_minutes: int = Query(default=10, ge=1, le=60),
    total_budget_sol: float = Query(default=0.03, gt=0, le=10),
    max_order_budget_sol: float = Query(default=0.01, gt=0, le=1),
    max_order_count: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
):
    try:
        return preview_micro_live_canary_permit(
            db,
            operational_assessment_id=operational_assessment_id,
            validity_minutes=validity_minutes,
            total_budget_sol=total_budget_sol,
            max_order_budget_sol=max_order_budget_sol,
            max_order_count=max_order_count,
        )
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-micro-live-canary/issue", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def issue_micro_live_canary_endpoint(
    request: CanonicalParserMicroLiveCanaryPermitIssueRequest,
    db: Session = Depends(get_db),
):
    try:
        return issue_micro_live_canary_permit(
            db,
            operational_assessment_id=request.operational_assessment_id,
            validity_minutes=request.validity_minutes,
            total_budget_sol=request.total_budget_sol,
            max_order_budget_sol=request.max_order_budget_sol,
            max_order_count=request.max_order_count,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-micro-live-canary/revoke", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def revoke_micro_live_canary_endpoint(
    request: CanonicalParserMicroLiveCanaryPermitRevokeRequest,
    db: Session = Depends(get_db),
):
    try:
        return revoke_micro_live_canary_permit(
            db,
            permit_id=request.permit_id,
            confirmation=request.confirmation,
            reason=request.reason,
            actor_label=request.actor_label,
        )
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-micro-live-canary/simulation-preview", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def preview_micro_live_canary_simulation_endpoint(
    permit_id: str = Query(min_length=36, max_length=36),
    decision_result_id: str = Query(min_length=36, max_length=36),
    side: str = Query(pattern="^(BUY|SELL)$"),
    market_price_sol: float = Query(gt=0, le=1_000_000_000),
    requested_budget_sol: float = Query(default=0.01, ge=0, le=10),
    idempotency_token: str = Query(min_length=8, max_length=200),
    db: Session = Depends(get_db),
):
    try:
        return preview_micro_live_canary_simulation(
            db,
            permit_id=permit_id,
            decision_result_id=decision_result_id,
            side=side,
            market_price_sol=market_price_sol,
            requested_budget_sol=requested_budget_sol,
            idempotency_token=idempotency_token,
        )
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.post("/integrity/parser-micro-live-canary/simulate", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def simulate_micro_live_canary_endpoint(
    request: CanonicalParserMicroLiveCanarySimulationRequest,
    db: Session = Depends(get_db),
):
    try:
        return simulate_micro_live_canary(
            db,
            permit_id=request.permit_id,
            decision_result_id=request.decision_result_id,
            side=request.side,
            market_price_sol=request.market_price_sol,
            requested_budget_sol=request.requested_budget_sol,
            idempotency_token=request.idempotency_token,
            confirmation=request.confirmation,
            actor_label=request.actor_label,
            note=request.note,
        )
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-micro-live-canary/permits/{permit_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_micro_live_canary_permit_endpoint(permit_id: str, db: Session = Depends(get_db)):
    try:
        return get_micro_live_canary_permit(db, permit_id)
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-micro-live-canary/simulations/{simulation_id}", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def read_micro_live_canary_simulation_endpoint(simulation_id: str, db: Session = Depends(get_db)):
    try:
        return get_micro_live_canary_simulation(db, simulation_id)
    except CanonicalParserMicroLiveCanaryError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={"code": exception.code, "message": str(exception)},
        ) from exception


@app.get("/integrity/parser-micro-live-canary/resolve", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])
def resolve_micro_live_canary_endpoint(db: Session = Depends(get_db)):
    return resolve_micro_live_canary(db)
# END M35 MICRO-LIVE CANARY GOVERNANCE & SIMULATION
