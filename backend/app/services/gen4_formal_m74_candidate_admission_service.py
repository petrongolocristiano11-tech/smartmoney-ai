from __future__ import annotations

from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

FORMAL_M74_ADMISSION_VERSION = "gen4-formal-m74-candidate-admission/2"
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


PENDING_FLAT_M74_TARGETED_REPORT_SHA256 = "e1f8aab7fdbeff94fd8927dba55c03fb4d564375bdbd332a9e413b70d945b8e6"
PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256 = "be808e1a2b8cd7a2855629b6f36e9be5bcb6f8bfc7260878d148c1c6be9e9813"
PENDING_FLAT_M74_STATE = "QUALIFIED_PENDING_FLAT"

PENDING_FLAT_M74_ADMITTED_WALLETS: dict[str, str] = {
    "3N7": "3N7aa2Wkg9dEm8kkC4F7M8knExDyEL8Vehu1S9H3NA2K",
    "2MQR": "2mqrindMAjJEQPLhroYWyiYPo5h9iAsahfdd4QtsjwdY",
}

# These wallets were evaluated with the unchanged canonical M74 evaluator.
# Their formal result remains FAIL_COMPLETE_HISTORY because the existing M74
# contract includes zero_open_positions.  This registry does NOT rewrite that
# history or claim a formal M74 PASS.  It records the narrower, independently
# verified fact that every M74 economic check except inventory flatness passed,
# and that the five historical positions are quarantined from all fresh
# candidate/full-lifecycle evidence.
PENDING_FLAT_M74_ADMISSION_EVIDENCE: dict[str, dict[str, Any]] = {
    PENDING_FLAT_M74_ADMITTED_WALLETS["3N7"]: {
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["3N7"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 157,
        "profit_factor": 3.61359228,
        "net_pnl_sol": 1.525179787,
        "maximum_drawdown_percent": 5.17888299,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["2MQR"]: {
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["2MQR"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 734,
        "profit_factor": 2.97184034,
        "net_pnl_sol": 3.167214088,
        "maximum_drawdown_percent": 3.60728645,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
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



def validate_pending_flat_m74_admission_registry() -> dict[str, dict[str, Any]]:
    _require(
        len(PENDING_FLAT_M74_ADMITTED_WALLETS) == 2,
        "Unexpected pending-flat M74 admission registry size.",
    )
    _require(
        set(PENDING_FLAT_M74_ADMITTED_WALLETS.values()).isdisjoint(
            FORMAL_M74_ADMITTED_WALLETS.values()
        ),
        "Formal PASS and pending-flat M74 registries must be disjoint.",
    )

    expected = {
        "3N7": {
            "closed_trade_count": 157,
            "profit_factor": 3.61359228,
            "net_pnl_sol": 1.525179787,
            "maximum_drawdown_percent": 5.17888299,
        },
        "2MQR": {
            "closed_trade_count": 734,
            "profit_factor": 2.97184034,
            "net_pnl_sol": 3.167214088,
            "maximum_drawdown_percent": 3.60728645,
        },
    }

    registry: dict[str, dict[str, Any]] = {}
    for label, wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        evidence = dict(PENDING_FLAT_M74_ADMISSION_EVIDENCE.get(wallet) or {})
        _require(evidence.get("wallet_address") == wallet, f"{label} pending-flat wallet evidence mismatch.")
        _require(evidence.get("qualification_state") == PENDING_FLAT_M74_STATE, f"{label} pending-flat state drift.")
        _require(evidence.get("formal_m74_pass") is False, f"{label} must not claim formal M74 PASS.")
        _require(evidence.get("formal_m74_status") == "FAIL_COMPLETE_HISTORY", f"{label} formal M74 status drift.")
        _require(evidence.get("formal_evaluator") == R7_FORMAL_EVALUATOR, f"{label} evaluator drift.")
        _require(
            list(evidence.get("formal_failure_reasons") or []) == ["zero_open_positions"],
            f"{label} is not a flatness-only M74 blocker.",
        )
        _require(evidence.get("history_complete") is True, f"{label} history must be complete.")
        _require(evidence.get("all_non_flatness_m74_checks_passed") is True, f"{label} non-flatness M74 checks not proven.")
        _require(evidence.get("flatness_only_blocker") is True, f"{label} flatness-only marker missing.")
        _require(int(evidence.get("open_positions") or 0) == 5, f"{label} open-position count drift.")
        _require(
            evidence.get("targeted_report_sha256") == PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
            f"{label} targeted report SHA drift.",
        )
        _require(
            evidence.get("root_cause_report_sha256") == PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
            f"{label} root-cause report SHA drift.",
        )
        _require(
            evidence.get("root_cause_classification") == "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
            f"{label} root-cause classification drift.",
        )
        _require(int(evidence.get("parser_gap_positions") or 0) == 0, f"{label} parser gap present.")
        _require(evidence.get("position_turnover") is False, f"{label} position turnover unexpectedly present.")
        _require(evidence.get("historical_open_positions_quarantined") is True, f"{label} historical positions not quarantined.")
        _require(
            evidence.get("historical_open_positions_followed_by_candidate_lane") is False,
            f"{label} candidate lane must not inherit historical positions.",
        )
        _require(evidence.get("candidate_forward_proof_backfilled") is False, f"{label} candidate proof backfill detected.")
        _require(evidence.get("m75_pass_claimed") is False, f"{label} M75 cannot be claimed.")
        _require(evidence.get("m298_pass_claimed") is False, f"{label} M298 cannot be claimed.")
        _require(evidence.get("gen4_copyability_pass_claimed") is False, f"{label} Gen4 PASS cannot be invented.")
        _require(evidence.get("live_execution_authorized") is False, f"{label} LIVE authorization cannot be inherited.")

        metrics = expected[label]
        _require(int(evidence.get("closed_trade_count") or 0) == metrics["closed_trade_count"], f"{label} closed count drift.")
        for key in ("profit_factor", "net_pnl_sol", "maximum_drawdown_percent"):
            _require(
                abs(float(evidence.get(key) or 0.0) - float(metrics[key])) < 1e-12,
                f"{label} {key} drift.",
            )
        registry[wallet] = evidence
    return registry


def pending_flat_m74_admitted_wallets() -> dict[str, str]:
    validate_pending_flat_m74_admission_registry()
    return dict(PENDING_FLAT_M74_ADMITTED_WALLETS)


def pending_flat_m74_admission_for_wallet(wallet: str) -> dict[str, Any] | None:
    registry = validate_pending_flat_m74_admission_registry()
    value = registry.get(str(wallet or "").strip())
    return dict(value) if value is not None else None

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
        "pending_flat_admitted_wallets": dict(PENDING_FLAT_M74_ADMITTED_WALLETS),
        "pending_flat_evidence": validate_pending_flat_m74_admission_registry(),
        "next_boundary": {
            "explicit_candidate_watchlist_mutation_required": True,
            "candidate_entry_evidence_must_be_new": True,
            "m300_attempt_floor_unchanged": True,
            "m300_accepted_floor_unchanged": True,
            "m300_quality_limits_unchanged": True,
            "m300_technical_reset_unchanged": True,
            "m298_full_lifecycle_not_started": True,
            "pending_flat_historical_positions_quarantined": True,
            "pending_flat_candidate_evidence_must_start_fresh": True,
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
