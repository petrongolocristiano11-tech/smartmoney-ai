from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models.candidate_exit_price_audit import CandidateExitPriceAuditRun
from backend.app.models.candidate_exitability_gate import CandidateExitabilityGateRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.services.candidate_backtest_service import MIN_SMART_SCORE
from backend.app.services.wallet_activity_service import safe_float


GATE_READY = "READY"
GATE_REVIEW = "REVIEW"
GATE_BLOCKED = "BLOCKED"
GATE_NOT_ANALYZED = "NON_ANALIZZATO"
GATE_REASON_PREFIX = "EXITABILITY_GATE_"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _latest_audits(db: Session, wallet_ids: list[str]) -> dict[str, CandidateExitPriceAuditRun]:
    if not wallet_ids:
        return {}
    rows = (
        db.query(CandidateExitPriceAuditRun)
        .filter(CandidateExitPriceAuditRun.wallet_address.in_(wallet_ids))
        .order_by(
            CandidateExitPriceAuditRun.wallet_address.asc(),
            CandidateExitPriceAuditRun.completed_at.desc(),
            CandidateExitPriceAuditRun.id.desc(),
        )
        .all()
    )
    result: dict[str, CandidateExitPriceAuditRun] = {}
    for row in rows:
        result.setdefault(row.wallet_address, row)
    return result


def _evaluate(wallet: DiscoveredWallet, audit: CandidateExitPriceAuditRun | None) -> dict:
    if audit is None:
        return {
            "status": GATE_NOT_ANALYZED,
            "score": 0.0,
            "eligible": False,
            "hard_blocked": False,
            "reasons": ["EXITABILITY_GATE_AUDIT_REQUIRED"],
            "audit_run_id": None,
        }

    summary = dict(audit.summary or {})
    diagnoses = set(audit.diagnoses or [])
    score = float(audit.readiness_score or 0)
    route = safe_float(summary.get("current_route_supported_percent"))
    temporal = safe_float(summary.get("temporal_execution_percent"))
    positions = int(summary.get("positions_analyzed") or 0)
    cache_missing = int(summary.get("cache_missing") or 0)

    hard_blocked = bool(
        positions > 0
        and str(audit.readiness_status) == "BLOCKED"
        and score <= 0
        and route <= 0
        and temporal <= 0
        and cache_missing == positions
        and "ALL_OPEN_POSITIONS_MISSING_CACHE" in diagnoses
    )

    if hard_blocked:
        status = GATE_BLOCKED
        eligible = False
        reasons = [
            "EXITABILITY_GATE_HARD_BLOCK",
            "EXITABILITY_ZERO_ROUTE_COVERAGE",
            "EXITABILITY_ZERO_TEMPORAL_EVIDENCE",
            "EXITABILITY_ALL_OPEN_POSITIONS_MISSING_CACHE",
        ]
    elif str(audit.readiness_status) == "READY" and score >= 80:
        status = GATE_READY
        eligible = True
        reasons = ["EXITABILITY_GATE_READY"]
    else:
        status = GATE_REVIEW
        eligible = False
        reasons = ["EXITABILITY_GATE_REVIEW_REQUIRED"]

    return {
        "status": status,
        "score": score,
        "eligible": eligible,
        "hard_blocked": hard_blocked,
        "reasons": reasons,
        "audit_run_id": audit.run_id,
    }


def _recalculate_overall_eligibility(wallet: DiscoveredWallet) -> None:
    wallet.eligible = bool(
        wallet.activity_eligible
        and wallet.quality_eligible
        and wallet.promotion_eligible
        and wallet.backtest_data_sufficient
        and safe_float(wallet.smart_score) >= MIN_SMART_SCORE
        and wallet.exitability_gate_eligible
    )
    preserved = [
        reason for reason in list(wallet.eligibility_reasons or [])
        if not str(reason).startswith(GATE_REASON_PREFIX)
        and not str(reason).startswith("EXITABILITY_")
    ]
    wallet.eligibility_reasons = list(dict.fromkeys(
        preserved + list(wallet.exitability_gate_reasons or [])
    ))


def run_exitability_gate_refresh(
    db: Session,
    *,
    limit: int = 250,
    now: datetime | None = None,
) -> CandidateExitabilityGateRun:
    started_at = now or utc_now()
    effective_limit = max(1, min(int(limit), 500))
    wallets = (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.ranking_score.desc(), DiscoveredWallet.smart_score.desc())
        .limit(effective_limit)
        .all()
    )
    audits = _latest_audits(db, [w.wallet_address for w in wallets])

    counts = {GATE_READY: 0, GATE_REVIEW: 0, GATE_BLOCKED: 0, GATE_NOT_ANALYZED: 0}
    results = []
    for wallet in wallets:
        outcome = _evaluate(wallet, audits.get(wallet.wallet_address))
        wallet.exitability_gate_status = outcome["status"]
        wallet.exitability_gate_score = outcome["score"]
        wallet.exitability_gate_eligible = outcome["eligible"]
        wallet.exitability_gate_reasons = outcome["reasons"]
        wallet.exitability_gate_calculated_at = started_at
        _recalculate_overall_eligibility(wallet)
        counts[outcome["status"]] += 1
        results.append({
            "wallet_address": wallet.wallet_address,
            **outcome,
            "final_eligible": bool(wallet.eligible),
        })

    run = CandidateExitabilityGateRun(
        run_id=str(uuid4()),
        status="COMPLETED",
        parameters={"limit": effective_limit},
        safety={
            "cached_only": True,
            "helius_requests": 0,
            "jupiter_live_requests": 0,
            "live_changed": False,
            "stream_changed": False,
            "worker_changed": False,
            "generation_changed": False,
            "promotion_status_changed": False,
        },
        summary={
            "wallets_evaluated": len(wallets),
            "wallets_ready": counts[GATE_READY],
            "wallets_review": counts[GATE_REVIEW],
            "wallets_blocked": counts[GATE_BLOCKED],
            "wallets_not_analyzed": counts[GATE_NOT_ANALYZED],
            "wallets_finally_eligible": sum(1 for row in results if row["final_eligible"]),
        },
        wallet_results=results,
        started_at=started_at,
        completed_at=started_at,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run
