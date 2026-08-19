from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-m65-not-used")

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_AUDIT_VERSION,
    calculate_trade_metrics,
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_definitive_wallet_gate_service import (  # noqa: E402
    M65DefinitiveGateError,
    M65_GATE_VERSION,
    evaluate_definitive_wallet_gate,
    verify_raw_evidence,
)
from scripts.run_m65_gen4_definitive_wallet_gate import (  # noqa: E402
    main as run_m65_gate,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "m65_gen4_definitive_wallet_gate.json"
)
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def trade(
    *,
    group: str,
    index: int,
    pnl: int,
    token_id: int,
    closed_at: datetime,
    cost_impact: dict | None = None,
) -> dict:
    cost = 10_100_000
    value = {
        "entry_signature": f"m65-{group}-entry-{index:03d}-sanitized",
        "last_exit_signature": f"m65-{group}-exit-{index:03d}-sanitized",
        "token_mint": f"M65SanitizedToken{token_id:02d}",
        "entry_signal_at": (closed_at - timedelta(minutes=5)).isoformat(),
        "closed_at": closed_at.isoformat(),
        "entry_sequence": index + 1,
        "close_sequence": index + 1,
        "pnl_lamports": pnl,
        "cost_lamports": cost,
        "fee_lamports": 200_000,
        "return_percent": pnl / cost * 100.0,
    }
    if cost_impact is not None:
        value["cost_impact"] = cost_impact
    value["evidence_sha256"] = canonical_sha256(value)
    return value


def current_rows() -> tuple[list[dict], list[dict], list[dict]]:
    data = fixture()
    official = [
        trade(
            group="official",
            index=index,
            pnl=pnl,
            token_id=data["official_token_ids"][index],
            closed_at=NOW + timedelta(seconds=index),
        )
        for index, pnl in enumerate(data["official_pnl_lamports"])
    ]
    impacts = {
        "slippage_impact_lamports": data[
            "reconstructed_slippage_impact_lamports"
        ],
        "fee_impact_lamports": data["reconstructed_fee_impact_lamports"],
        "total_cost_impact_lamports": data[
            "reconstructed_total_cost_impact_lamports"
        ],
        "interaction_lamports": 0,
        "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
    }
    reconstructed = [
        trade(
            group="reconstructed",
            index=index,
            pnl=pnl,
            token_id=data["reconstructed_token_ids"][index],
            closed_at=NOW + timedelta(seconds=100 + index),
            cost_impact=(
                impacts
                if index == 0
                else {
                    "slippage_impact_lamports": 0,
                    "fee_impact_lamports": 0,
                    "total_cost_impact_lamports": 0,
                    "interaction_lamports": 0,
                    "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
                }
            ),
        )
        for index, pnl in enumerate(data["reconstructed_pnl_lamports"])
    ]
    supplemental = [
        trade(
            group="supplemental",
            index=index,
            pnl=pnl,
            token_id=data["supplemental_token_ids"][index],
            closed_at=NOW + timedelta(seconds=116),
            cost_impact={
                "slippage_impact_lamports": 0,
                "fee_impact_lamports": 0,
                "total_cost_impact_lamports": 0,
                "interaction_lamports": 0,
                "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
            },
        )
        for index, pnl in enumerate(data["supplemental_pnl_lamports"])
    ]
    return official, reconstructed, supplemental


def passing_rows() -> tuple[list[dict], list[dict], list[dict]]:
    pnls = [1_500_000 if index % 5 != 4 else -1_000_000 for index in range(100)]
    all_rows = [
        trade(
            group="passing",
            index=index,
            pnl=pnl,
            token_id=(index % 10) + 1,
            closed_at=NOW + timedelta(seconds=index),
            cost_impact=(
                {
                    "slippage_impact_lamports": 50_000,
                    "fee_impact_lamports": 200_000,
                    "total_cost_impact_lamports": 250_000,
                    "interaction_lamports": 0,
                    "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
                }
                if index >= 83
                else None
            ),
        )
        for index, pnl in enumerate(pnls)
    ]
    return all_rows[:83], all_rows[83:], []


def audit_report(*, passing: bool = False) -> dict:
    official, reconstructed, supplemental = (
        passing_rows() if passing else current_rows()
    )
    official_metrics = calculate_trade_metrics(
        official,
        evidence_quality="EXACT_PRODUCTION_READ_ONLY",
    )
    reconstructed_metrics = calculate_trade_metrics(
        reconstructed,
        evidence_quality="ESTIMATED_SAME_TRANSACTION_ONCHAIN_PROXY",
    )
    combined_metrics = calculate_trade_metrics(
        official + reconstructed,
        evidence_quality="MIXED_83_EXACT_PLUS_RECONSTRUCTED_PROXY",
    )
    complete_reconstructed = reconstructed + supplemental
    complete_batch_metrics = calculate_trade_metrics(
        official + complete_reconstructed,
        evidence_quality="MIXED_83_EXACT_PLUS_COMPLETE_CLOSE_BATCH_SENSITIVITY",
    )
    complete_reconstructed_metrics = calculate_trade_metrics(
        complete_reconstructed,
        evidence_quality="ESTIMATED_COMPLETE_CUTOFF_CLOSE_BATCH_SENSITIVITY",
    )
    data = fixture()
    open_positions = [] if passing else [
        {
            "entry_signature": f"m65-open-{index}",
            "token_mint": "M65SanitizedToken10",
        }
        for index in range(data["open_position_count"])
    ]
    result = {
        "audit": "PASS",
        "scope": "M64_GEN4_83_PLUS_RECONSTRUCTED_CLOSED_TRADES_READ_ONLY",
        "audit_version": M64_AUDIT_VERSION,
        "source": {
            "parser_version": "canonical-parser-gen4-raw-balance-delta/4",
            "policy_version": "canonical-parser-gen4-realtime-copyability/1",
            "raw_evidence_sha256": "a" * 64,
        },
        "safety": {
            "helius_requests": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "railway_mutations": 0,
            "jupiter_historical_quote_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_access": False,
            "official_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
        },
        "campaign": {
            "campaign_id": "e5eaf7b6-a4e7-4182-96a2-d5f6af668e74",
            "wallet": data["wallet"],
            "policy_snapshot": {
                "policy_version": "canonical-parser-gen4-realtime-copyability/1"
            },
        },
        "public_rpc": {"history_complete": True},
        "parser": {"rejected_transaction_count": 15},
        "samples": {
            "official_realtime": {
                "closed_trade_count": 83,
                "evidence_class": "OFFICIAL_REALTIME",
                "metrics": official_metrics,
                "trades": official,
                "entry_reject_rate_percent": data[
                    "official_entry_reject_rate_percent"
                ],
            },
            "reconstructed": {
                "closed_trade_count": 17,
                "target_closed_trade_count": 17,
                "target_reached": True,
                "evidence_class": "RECOVERY_ANALYTIC_ONLY_NOT_REALTIME_PROOF",
                "metrics": reconstructed_metrics,
                "trades": reconstructed,
                "open_positions_at_end": open_positions,
                "historical_entry_admission": {
                    "status": "NOT_RECONSTRUCTIBLE_WITHOUT_HISTORICAL_JUPITER_QUOTES",
                    "entry_reject_rate_percent": None,
                },
            },
            "combined_equivalent": {
                "closed_trade_count": 100,
                "target_100_reached": True,
                "evidence_class": "ANALYTIC_EQUIVALENT_NOT_OFFICIAL_REALTIME_PROOF",
                "metrics": combined_metrics,
            },
            "cutoff_complete_batch_sensitivity": {
                "closed_trade_count": 100 + len(supplemental),
                "reconstructed_closed_trade_count": len(complete_reconstructed),
                "target_cut_through_close_batch": bool(supplemental),
                "supplemental_cutoff_batch_trade_count": len(supplemental),
                "evidence_class": "ANALYTIC_CUTOFF_BATCH_SENSITIVITY_NOT_REALTIME_PROOF",
                "reconstructed_metrics": complete_reconstructed_metrics,
                "combined_metrics": complete_batch_metrics,
                "supplemental_trades": supplemental,
            },
        },
        "reconstruction": {
            "open_positions_at_end": open_positions,
            "target_cut_through_close_batch": bool(supplemental),
        },
        "artifacts": {
            "raw_evidence_filename": "m65-sanitized-raw.json",
            "raw_evidence_sha256": "a" * 64,
        },
    }
    result["integrity"] = {
        "report_payload_sha256": canonical_sha256(result),
        "full_signatures_preserved": True,
        "raw_transaction_hashes_preserved": True,
    }
    return result


def passing_canary(wallet: str) -> dict:
    result = {
        "scope": "M65_REALTIME_CANARY_EVIDENCE",
        "wallet": wallet,
        "observation_hours": 24.0,
        "entry_attempt_count": 25,
        "closed_trade_count": 15,
        "webhook_coverage_percent": 98.0,
        "unsigned_build_coverage_percent": 100.0,
        "entry_reject_rate_percent": 8.0,
        "p95_end_to_quote_ms": 900.0,
        "p95_price_impact_bps": 120.0,
        "p95_price_deterioration_bps": 350.0,
        "open_position_count": 0,
        "unresolved_failure_count": 0,
        "safety": {
            "signer_access": False,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
        },
    }
    result["evidence_sha256"] = canonical_sha256(result)
    return result


def raw_evidence() -> dict:
    result = {
        "scope": "M64_PUBLIC_FINALIZED_RAW_EVIDENCE",
        "boundary_reached": True,
        "signature_limit_reached": False,
        "unavailable_signatures": [],
        "helius_requests": 0,
        "backend_posts": 0,
        "database_writes": 0,
    }
    result["payload_sha256"] = canonical_sha256(result)
    return result


def test_current_candidate_regression_is_fail_closed_with_exact_core_metrics():
    data = fixture()
    result = evaluate_definitive_wallet_gate(
        audit_report(),
        evaluated_at=NOW,
    )

    assert result["gate"] == data["expected"]["verdict"]
    assert result["analytics"]["combined"]["net_pnl_lamports"] == data[
        "expected"
    ]["combined_net_pnl_lamports"]
    assert result["analytics"]["combined"]["profit_factor"] == pytest.approx(
        data["expected"]["combined_profit_factor"]
    )
    assert result["analytics"]["recent_reconstructed"][
        "net_pnl_lamports"
    ] == data["expected"]["reconstructed_net_pnl_lamports"]
    assert result["analytics"]["complete_cutoff_batch"][
        "profit_factor"
    ] == pytest.approx(data["expected"]["complete_batch_profit_factor"])
    assert set(data["expected"]["required_failure_reasons"]).issubset(
        result["economic_failure_reasons"]
    )
    assert result["candidate"]["recommended_state"] == (
        "RESEARCH_ONLY_RECENT_STABILITY_FAILED"
    )
    assert result["verdict"]["micro_live_execution_authorized"] is False


def test_economic_pass_without_canary_is_conditional_and_never_auto_live():
    result = evaluate_definitive_wallet_gate(
        audit_report(passing=True),
        evaluated_at=NOW,
    )

    assert result["economic_failure_reasons"] == []
    assert result["gate"] == "CONDITIONAL_PASS_CANARY_REQUIRED"
    assert result["canary"]["status"] == "MISSING"
    assert result["verdict"]["micro_live_preparation_allowed"] is False
    assert result["verdict"]["automatic_live_activation"] is False


def test_economic_and_canary_pass_only_allow_preparation_not_execution():
    report = audit_report(passing=True)
    wallet = report["campaign"]["wallet"]
    result = evaluate_definitive_wallet_gate(
        report,
        canary_evidence=passing_canary(wallet),
        evaluated_at=NOW,
    )

    assert result["gate"] == "PASS_FOR_MICRO_LIVE_PREPARATION"
    assert result["canary"]["status"] == "PASS"
    assert result["verdict"]["micro_live_preparation_allowed"] is True
    assert result["verdict"]["micro_live_execution_authorized"] is False
    assert result["verdict"]["signer_authorized"] is False


def test_canary_failure_cannot_be_hidden_by_strong_history():
    report = audit_report(passing=True)
    canary = passing_canary(report["campaign"]["wallet"])
    canary["webhook_coverage_percent"] = 50.0
    canary["evidence_sha256"] = canonical_sha256(
        {key: value for key, value in canary.items() if key != "evidence_sha256"}
    )
    result = evaluate_definitive_wallet_gate(
        report,
        canary_evidence=canary,
        evaluated_at=NOW,
    )

    assert result["gate"] == "FAIL_CANARY"
    assert "CANARY_WEBHOOK_COVERAGE_BELOW_MINIMUM" in result["canary"][
        "failure_reasons"
    ]
    assert result["candidate"]["recommended_state"] == "REALTIME_CANARY_FAILED"
    assert result["verdict"]["next_step"] == (
        "REMEDIATE_AND_REPEAT_REALTIME_CANARY"
    )


def test_report_tampering_and_safety_mutation_are_rejected():
    tampered = audit_report()
    tampered["samples"]["combined_equivalent"]["metrics"][
        "profit_factor"
    ] = 99.0
    with pytest.raises(M65DefinitiveGateError):
        evaluate_definitive_wallet_gate(tampered, evaluated_at=NOW)

    unsafe = audit_report()
    unsafe["safety"]["live_orders"] = 1
    unsafe["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in unsafe.items() if key != "integrity"}
    )
    with pytest.raises(M65DefinitiveGateError):
        evaluate_definitive_wallet_gate(unsafe, evaluated_at=NOW)

    duplicate = audit_report()
    duplicate["samples"]["reconstructed"]["trades"][0]["entry_signature"] = (
        duplicate["samples"]["official_realtime"]["trades"][0][
            "entry_signature"
        ]
    )
    duplicated_trade = duplicate["samples"]["reconstructed"]["trades"][0]
    duplicated_trade["evidence_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in duplicated_trade.items()
            if key != "evidence_sha256"
        }
    )
    duplicate["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in duplicate.items() if key != "integrity"}
    )
    with pytest.raises(M65DefinitiveGateError):
        evaluate_definitive_wallet_gate(duplicate, evaluated_at=NOW)

    mismatched_raw_hash = audit_report()
    mismatched_raw_hash["artifacts"]["raw_evidence_sha256"] = "b" * 64
    mismatched_raw_hash["integrity"]["report_payload_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in mismatched_raw_hash.items()
            if key != "integrity"
        }
    )
    with pytest.raises(M65DefinitiveGateError):
        evaluate_definitive_wallet_gate(mismatched_raw_hash, evaluated_at=NOW)


def test_raw_evidence_contract_is_hash_bound_and_fail_closed():
    raw = raw_evidence()
    verification = verify_raw_evidence(
        raw,
        expected_file_sha256="a" * 64,
    )
    assert verification["boundary_reached"] is True

    raw["database_writes"] = 1
    raw["payload_sha256"] = canonical_sha256(
        {key: value for key, value in raw.items() if key != "payload_sha256"}
    )
    with pytest.raises(M65DefinitiveGateError):
        verify_raw_evidence(raw, expected_file_sha256="a" * 64)


def test_gate_policy_version_cannot_be_silently_replaced():
    with pytest.raises(M65DefinitiveGateError):
        evaluate_definitive_wallet_gate(
            audit_report(),
            gate_policy={"policy_version": M65_GATE_VERSION + "-tampered"},
            evaluated_at=NOW,
        )


def test_runner_binds_exact_m64_pair_and_writes_hashed_fail_closed_report(
    tmp_path,
    monkeypatch,
    capsys,
):
    raw = raw_evidence()
    raw_path = tmp_path / "m65-sanitized-raw.json"
    write_json_atomic(raw_path, raw)
    raw_file_hash = file_sha256(raw_path)

    report = audit_report()
    report["source"]["raw_evidence_sha256"] = raw_file_hash
    report["artifacts"]["raw_evidence_filename"] = raw_path.name
    report["artifacts"]["raw_evidence_sha256"] = raw_file_hash
    report["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "integrity"}
    )
    audit_path = tmp_path / "m65-sanitized-audit.json"
    write_json_atomic(audit_path, report)
    output_dir = tmp_path / "gate-output"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_m65_gen4_definitive_wallet_gate.py",
            "--confirmation",
            "RUN_M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE",
            "--audit-report",
            str(audit_path),
            "--raw-evidence",
            str(raw_path),
            "--output-dir",
            str(output_dir),
        ],
    )
    assert run_m65_gate() == 0
    stdout = capsys.readouterr().out
    assert "GATE_VERDICT=FAIL_ECONOMIC" in stdout
    assert "MICRO_LIVE_EXECUTION_AUTHORIZED=NO" in stdout
    assert "HELIUS_REQUESTS=0" in stdout

    outputs = list(output_dir.glob("smartmoney-m65-definitive-wallet-gate-*.json"))
    assert len(outputs) == 1
    generated = json.loads(outputs[0].read_text(encoding="utf-8"))
    assert generated["gate"] == "FAIL_ECONOMIC"
    assert generated["raw_evidence_verification"]["file_sha256"] == (
        raw_file_hash
    )
    assert generated["integrity"]["gate_payload_sha256"] == canonical_sha256(
        {key: value for key, value in generated.items() if key != "integrity"}
    )
