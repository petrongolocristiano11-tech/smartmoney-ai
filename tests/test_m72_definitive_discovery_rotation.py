from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.run_m72_definitive_discovery_rotation as m72_runner

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_definitive_discovery_rotation_service import (
    DISPOSITION_OBSERVE,
    DISPOSITION_QUALIFIED,
    DISPOSITION_RETIRE,
    M72DiscoveryRotationError,
    M72_FUTURE_HELIUS_CONFIRMATION,
    M72_RUN_CONFIRMATION,
    build_rotation_report,
    classify_active_candidate,
    validate_acquisition_plan,
    validate_rotation_report,
)
from backend.app.services.gen4_zero_helius_adaptive_continuation_service import (
    M71_SCOPE,
    M71_VERSION,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_RPC_SCOPE,
    M67_M70_SCOPE,
    M67_M70_VERSION,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "m72_definitive_discovery_rotation.json"
NOW = datetime(2026, 8, 15, 14, 0, tzinfo=timezone.utc)


def _load_fixture() -> dict:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected = fixture["integrity"]["fixture_sha256"]
    payload = {key: value for key, value in fixture.items() if key != "integrity"}
    assert expected == canonical_sha256(payload)
    return fixture


def _safety(*, public_rpc_requests: int = 0) -> dict:
    return {
        "network_requests": public_rpc_requests,
        "public_rpc_requests": public_rpc_requests,
        "helius_requests": 0,
        "helius_credits": 0,
        "database_reads": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "micro_live_execution_authorized": False,
    }


def _events(row: dict) -> list[dict]:
    return [
        {"side": "BUY", "signature": f"buy-{index}"}
        for index in range(int(row["buy_events"]))
    ] + [
        {"side": "SELL", "signature": f"sell-{index}"}
        for index in range(int(row["sell_events"]))
    ]


def _metrics(row: dict) -> dict:
    return {
        "closed_trade_count": int(row.get("closed_trade_count") or 0),
        "open_positions": int(row.get("open_positions") or 0),
        "net_pnl_sol": float(row.get("net_pnl_sol") or 0.0),
        "net_equity_pnl_sol": float(row.get("net_equity_pnl_sol") or 0.0),
        "profit_factor": float(row.get("profit_factor") or 0.0),
        "win_rate_percent": float(row.get("win_rate_percent") or 0.0),
        "maximum_drawdown_percent": float(
            row.get("maximum_drawdown_percent") or 0.0
        ),
        "history_span_days": float(row.get("history_span_days") or 0.0),
    }


def _signed_inputs() -> tuple[dict, dict, dict]:
    fixture = _load_fixture()
    activity: dict[str, dict] = {}
    deep: dict[str, dict] = {}
    candidates: list[dict] = []
    for row in fixture["active_candidates"]:
        wallet = str(row["wallet_address"])
        activity[wallet] = {
            "activity_status": "ACTIVE_CANDIDATE",
            "deep_history_candidate": True,
            "active_days_7d": 5,
            "transactions_7d": 20,
        }
        metrics = _metrics(row)
        events = _events(row)
        deep[wallet] = {
            "wallet_address": wallet,
            "history_complete": bool(row["history_complete"]),
            "signature_count": int(row["transaction_count"]),
            "transaction_count": int(row["transaction_count"]),
            "parsed_event_count": int(row["parsed_event_count"]),
            "events": events,
            "backtest": {"metrics": metrics},
        }
        candidates.append(
            {
                "wallet_address": wallet,
                "status": "NEEDS_MORE_PUBLIC_RPC_HISTORY",
                "reason": "PUBLIC_RPC_POSITION_HISTORY_INCOMPLETE",
                "activity": activity[wallet],
                "economic_analysis": {
                    "metrics": metrics,
                    "recent_metrics": {},
                },
                "m65_gate": {},
            }
        )
    research_wallet = str(fixture["research_only_wallet"])
    candidates.append(
        {
            "wallet_address": research_wallet,
            "status": "RESEARCH_ONLY",
            "reason": "M65_DEFINITIVE_ECONOMIC_FAIL",
            "activity": {"deep_history_candidate": False},
            "economic_analysis": None,
            "m65_gate": {
                "status": "FAIL_ECONOMIC",
                "recommended_state": "RESEARCH_ONLY",
            },
        }
    )
    rpc = {
        "scope": M67_M70_RPC_SCOPE,
        "version": M67_M70_VERSION,
        "collected_at_utc": NOW.isoformat(),
        "activity": activity,
        "deep_history": deep,
        "rpc": {"requests": 7, "request_cap": 500},
        "cache": {"schema": "fixture", "entry_count": 7, "payload_sha256": "a" * 64},
        "policy_sha256": "b" * 64,
        "safety": _safety(public_rpc_requests=7),
    }
    rpc["integrity"] = {"rpc_evidence_sha256": canonical_sha256(rpc)}
    summary = {
        "wallets_evaluated": 7,
        "active_public_rpc_candidates": 6,
        "deep_wallets_analyzed": 6,
        "wallets_qualified_pending_canary": 0,
        "selected_wallets": 0,
    }
    m67 = {
        "evaluation": "PASS",
        "scope": M67_M70_SCOPE,
        "version": M67_M70_VERSION,
        "evaluated_at_utc": NOW.isoformat(),
        "source": {"rpc_evidence_sha256": rpc["integrity"]["rpc_evidence_sha256"]},
        "summary": summary,
        "policy": {},
        "candidate_results": candidates,
        "selected_wallets": [],
        "multi_wallet_consensus": {"minimum_reached": False},
        "safety": _safety(),
    }
    m67["integrity"] = {"report_payload_sha256": canonical_sha256(m67)}
    m71 = {
        "evaluation": "PASS",
        "scope": M71_SCOPE,
        "version": M71_VERSION,
        "evaluated_at_utc": NOW.isoformat(),
        "strict_official_counter_correction": {
            "official_realtime_counter": 83,
            "production_counter_mutated": False,
        },
        "updated_qualification": {
            "summary": summary,
            "candidate_results": candidates,
            "selected_wallets": [],
            "multi_wallet_consensus": {"minimum_reached": False},
        },
        "decision": {"micro_live_execution_authorized": False},
        "safety": _safety(public_rpc_requests=7),
    }
    m71["integrity"] = {"report_payload_sha256": canonical_sha256(m71)}
    return m71, m67, rpc


def test_real_shape_rotation_is_two_observe_four_retired_and_one_locked() -> None:
    fixture = _load_fixture()
    report, plan = build_rotation_report(*_signed_inputs(), evaluated_at=NOW)
    validate_rotation_report(report)
    validate_acquisition_plan(plan)
    assert report["rotation_summary"] == fixture["expected_summary"]
    observed = {
        row["wallet_address"]: (row["disposition"], row["reason"])
        for row in report["wallet_rotation"]
    }
    assert observed == {
        row["wallet_address"]: (
            row["expected_disposition"],
            row["expected_reason"],
        )
        for row in fixture["active_candidates"]
    }
    assert report["research_only_locked"][0]["wallet_address"] == fixture[
        "research_only_wallet"
    ]


def test_complete_history_has_accurate_non_generic_dispositions() -> None:
    report, _ = build_rotation_report(*_signed_inputs(), evaluated_at=NOW)
    complete = [row for row in report["wallet_rotation"] if row["history_complete"]]
    assert complete
    assert all("INCOMPLETE_HISTORY" not in row["reason"] for row in complete)
    assert all(row["disposition"] in {DISPOSITION_OBSERVE, DISPOSITION_RETIRE} for row in complete)


def test_all_gen4_gates_and_complete_history_are_required_for_qualification() -> None:
    row = {
        "wallet_address": "qualified-wallet",
        "activity": {"deep_history_candidate": True},
        "economic_analysis": {
            "metrics": {
                "closed_trade_count": 100,
                "open_positions": 0,
                "net_pnl_sol": 1.0,
                "profit_factor": 1.4,
                "win_rate_percent": 40.0,
                "maximum_drawdown_percent": 10.0,
                "history_span_days": 31.0,
            },
            "recent_metrics": {
                "closed_trade_count": 20,
                "profit_factor": 1.2,
                "maximum_drawdown_percent": 8.0,
            },
        },
    }
    deep = {
        "history_complete": True,
        "transaction_count": 120,
        "parsed_event_count": 120,
        "events": [{"side": "BUY"}] * 60 + [{"side": "SELL"}] * 60,
    }
    assert classify_active_candidate(row, deep)["disposition"] == DISPOSITION_QUALIFIED
    deep["history_complete"] = False
    assert classify_active_candidate(row, deep)["disposition"] != DISPOSITION_QUALIFIED


def test_acquisition_plan_is_explicitly_disarmed_and_bounded() -> None:
    _, plan = build_rotation_report(*_signed_inputs(), evaluated_at=NOW)
    assert plan["state"] == "PREPARED_DISARMED"
    assert plan["required_manual_confirmation"] == M72_FUTURE_HELIUS_CONFIRMATION
    assert plan["execution_authorized"] is False
    assert plan["execution_performed"] is False
    assert plan["provider"]["maximum_requests"] == 6
    assert plan["provider"]["credit_cap"] == 600
    assert plan["provider"]["retries"] == 0
    assert plan["safety"]["helius_requests"] == 0
    assert plan["safety"]["helius_credits"] == 0


def test_cross_link_tampering_fails_closed() -> None:
    m71, m67, rpc = _signed_inputs()
    m67["source"]["rpc_evidence_sha256"] = "0" * 64
    m67["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in m67.items() if key != "integrity"}
    )
    with pytest.raises(M72DiscoveryRotationError, match="non collegato"):
        build_rotation_report(m71, m67, rpc, evaluated_at=NOW)


def test_runner_writes_only_signed_local_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    m71, m67, rpc = _signed_inputs()
    inputs = tmp_path / "inputs"
    output = tmp_path / "outputs"
    inputs.mkdir()
    paths = []
    for name, payload in (("m71.json", m71), ("m67.json", m67), ("rpc.json", rpc)):
        path = inputs / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths.append(path)
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_m72_definitive_discovery_rotation.py",
            "--confirmation",
            M72_RUN_CONFIRMATION,
            "--output-dir",
            str(output),
            "--m71-report",
            str(paths[0]),
            "--updated-m67-report",
            str(paths[1]),
            "--updated-rpc-evidence",
            str(paths[2]),
        ],
    )
    assert m72_runner.main() == 0
    generated = sorted(output.glob("*.json"))
    assert len(generated) == 2
    report = json.loads(next(path for path in generated if "rotation-report" in path.name).read_text())
    assert report["safety"]["network_requests"] == 0
    assert report["rotation_summary"]["observe_only"] == 2


def test_runner_requires_exact_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "run_m72_definitive_discovery_rotation.py",
            "--output-dir",
            str(tmp_path),
            "--m71-report",
            "missing.json",
            "--updated-m67-report",
            "missing.json",
            "--updated-rpc-evidence",
            "missing.json",
        ],
    )
    with pytest.raises(M72DiscoveryRotationError, match="Conferma richiesta"):
        m72_runner.main()
