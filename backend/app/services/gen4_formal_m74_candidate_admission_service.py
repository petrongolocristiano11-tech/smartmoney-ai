from __future__ import annotations

from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

FORMAL_M74_ADMISSION_VERSION = "gen4-formal-m74-candidate-admission/1"
FORMAL_M74_ADMISSION_SCOPE = "FORMAL_M74_PASS_TO_FASTPATH_CANDIDATE_ADMISSION_DISARMED"
FORMAL_M74_ADMISSION_ARMED = False
FORMAL_M74_AUTOMATIC_WATCHLIST_MUTATION = False
FORMAL_M74_AUTOMATIC_PROVIDER_MUTATION = False
FORMAL_M74_PRE_ADMISSION_BACKFILL = False

R7_FIX1_SCRIPT_SHA256 = "0d773bb72913cd8eded637357b1ac0c78caa7fe119be3ea26e6bfe429e4c9a0f"
R7_FORMAL_REPORT_SHA256 = "4636f386775669ff089c4c8fb4f233d7374afca32bf751f4e1063b589eeaa536"
R7_FORMAL_EVALUATOR = "evaluate_m74_candidate"

FORMAL_M74_ADMITTED_WALLETS: dict[str, str] = {
    "5PA": "5pAewyzzyf3bbD2MEdvEjTHR9AqfL9wWouEA8ft2ggEV",
}

# Immutable admission evidence copied from the verified R7 formal report.  This
# does not recompute or weaken M74.  It binds the admitted wallet to one exact
# previously-evaluated formal PASS artifact.
FORMAL_M74_ADMISSION_EVIDENCE: dict[str, dict[str, Any]] = {
    FORMAL_M74_ADMITTED_WALLETS["5PA"]: {
        "wallet_address": FORMAL_M74_ADMITTED_WALLETS["5PA"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "r7_fix1_script_sha256": R7_FIX1_SCRIPT_SHA256,
        "r7_formal_report_sha256": R7_FORMAL_REPORT_SHA256,
        "closed_trade_count": 524,
        "history_span_days": 35.00766204,
        "profit_factor": 16.04721544,
        "net_pnl_sol": 9.01787482,
        "maximum_drawdown_percent": 3.31264317,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
}


class FormalM74CandidateAdmissionError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FormalM74CandidateAdmissionError(message)


def validate_formal_m74_admission_registry() -> dict[str, dict[str, Any]]:
    _require(FORMAL_M74_ADMISSION_ARMED is False, "Formal M74 admission must remain disarmed.")
    _require(
        FORMAL_M74_AUTOMATIC_WATCHLIST_MUTATION is False,
        "Formal M74 admission must not mutate the candidate watchlist automatically.",
    )
    _require(
        FORMAL_M74_AUTOMATIC_PROVIDER_MUTATION is False,
        "Formal M74 admission must not mutate provider configuration automatically.",
    )
    _require(FORMAL_M74_PRE_ADMISSION_BACKFILL is False, "Formal M74 backfill must remain disabled.")
    _require(len(FORMAL_M74_ADMITTED_WALLETS) == 1, "Unexpected formal M74 admission registry size.")

    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    evidence = dict(FORMAL_M74_ADMISSION_EVIDENCE.get(wallet) or {})
    _require(evidence.get("wallet_address") == wallet, "Formal M74 wallet evidence mismatch.")
    _require(evidence.get("formal_m74_pass") is True, "Formal M74 PASS evidence missing.")
    _require(evidence.get("formal_m74_status") == "PASS", "Formal M74 status is not PASS.")
    _require(evidence.get("formal_evaluator") == R7_FORMAL_EVALUATOR, "Formal M74 evaluator drift.")
    _require(evidence.get("r7_fix1_script_sha256") == R7_FIX1_SCRIPT_SHA256, "R7 FIX1 SHA drift.")
    _require(evidence.get("r7_formal_report_sha256") == R7_FORMAL_REPORT_SHA256, "R7 report SHA drift.")
    _require(int(evidence.get("closed_trade_count") or 0) == 524, "Formal M74 closed count drift.")
    _require(abs(float(evidence.get("history_span_days") or 0.0) - 35.00766204) < 1e-12, "Formal M74 span drift.")
    _require(abs(float(evidence.get("profit_factor") or 0.0) - 16.04721544) < 1e-12, "Formal M74 PF drift.")
    _require(abs(float(evidence.get("net_pnl_sol") or 0.0) - 9.01787482) < 1e-12, "Formal M74 net PnL drift.")
    _require(abs(float(evidence.get("maximum_drawdown_percent") or 0.0) - 3.31264317) < 1e-12, "Formal M74 DD drift.")
    _require(int(evidence.get("open_positions") if evidence.get("open_positions") is not None else -1) == 0, "Formal M74 report must have zero open positions.")
    _require(evidence.get("historical_evidence_only") is True, "Historical evidence boundary missing.")
    _require(evidence.get("candidate_forward_proof_backfilled") is False, "Candidate proof backfill detected.")
    _require(evidence.get("m75_pass_claimed") is False, "M75 cannot be claimed by M74 admission.")
    _require(evidence.get("m298_pass_claimed") is False, "M298 cannot be claimed by M74 admission.")
    _require(evidence.get("gen4_copyability_pass_claimed") is False, "Gen4 copyability PASS cannot be invented.")
    _require(evidence.get("live_execution_authorized") is False, "LIVE authorization cannot be inherited.")
    return {wallet: evidence}


def formal_m74_admitted_wallets() -> dict[str, str]:
    validate_formal_m74_admission_registry()
    return dict(FORMAL_M74_ADMITTED_WALLETS)


def formal_m74_admission_for_wallet(wallet: str) -> dict[str, Any] | None:
    registry = validate_formal_m74_admission_registry()
    value = registry.get(str(wallet or "").strip())
    return dict(value) if value is not None else None


def build_formal_m74_admission_report() -> dict[str, Any]:
    registry = validate_formal_m74_admission_registry()
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": FORMAL_M74_ADMISSION_SCOPE,
        "version": FORMAL_M74_ADMISSION_VERSION,
        "armed": False,
        "admitted_wallets": dict(FORMAL_M74_ADMITTED_WALLETS),
        "evidence": registry,
        "next_boundary": {
            "explicit_candidate_watchlist_mutation_required": True,
            "candidate_entry_evidence_must_be_new": True,
            "m300_attempt_floor_unchanged": True,
            "m300_accepted_floor_unchanged": True,
            "m300_quality_limits_unchanged": True,
            "m300_technical_reset_unchanged": True,
            "m298_full_lifecycle_not_started": True,
        },
        "safety": {
            "database_writes": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "jupiter_requests": 0,
            "pre_admission_backfill": False,
            "gen4_copyability_pass_invented": False,
            "m75_changed": False,
            "m298_changed": False,
            "pam_changed": False,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload
