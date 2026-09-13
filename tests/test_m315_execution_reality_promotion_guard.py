from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import inspect

import backend.app.services.gen4_m315_execution_reality_promotion_guard_service as guard
import backend.app.services.gen4_promoted_selective_lifecycle_service as m307


WALLET = "GmRKk85gpi21Bti8z95fp3iWAGycAMJDz7uZKpAw1TF8"


def _row(i: int, *, pnl: int, status: str = "CLOSED", failures=None):
    anchor = datetime.fromisoformat(guard.M314_FRESH_ANCHOR_UTC)
    opened = anchor + timedelta(minutes=i + 1)
    closed = opened + timedelta(minutes=1)
    state = {
        "version": guard.M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": guard.M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "strict_forward_only": True,
        "backfill": False,
        "status": status,
        "position_id": f"P{i}",
        "wallet_address": WALLET,
        "token_mint": f"TOKEN{i}",
        "entry_signature": f"BUY{i}",
        "entry_received_at": opened.isoformat(),
        "opened_at": opened.isoformat(),
        "closed_at": closed.isoformat() if status == "CLOSED" else None,
        "entry_input_lamports": 10_000_000,
        "entry_output_token_raw": 1_000_000,
        "remaining_token_raw": 0 if status == "CLOSED" else 1_000_000,
        "allocated_entry_fee_lamports": 100_000,
        "realized_output_lamports": 0,
        "allocated_exit_fee_lamports": 0,
        "pnl_lamports": pnl if status == "CLOSED" else None,
        "return_percent": None,
        "exit_copyable": status == "CLOSED",
        "exit_failures": list(failures or []),
    }
    return SimpleNamespace(
        event_id=f"E{i}",
        evidence={guard.M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY: state},
    )


def _terminal() -> datetime:
    return datetime.fromisoformat(guard.M314_FRESH_ANCHOR_UTC) + timedelta(hours=3)


def test_m315_guard_can_pass_strict_forward_roundtrips_without_authorizing_automatic_promotion():
    rows = [_row(i, pnl=(2_000_000 if i < 8 else -500_000)) for i in range(10)]
    result = guard.build_m315_execution_reality_guard(
        wallet=WALLET,
        events=rows,
        evaluated_at=_terminal(),
    )
    assert result["passed"] is True
    assert result["manual_m307_prerequisite_satisfied"] is True
    assert result["guard_armed"] is False
    assert result["safety"]["automatic_promotion"] is False
    assert result["checks"]["zero_technical_exit_failures"] is True
    assert result["checks"]["zero_open_positions"] is True
    guard.validate_m315_execution_reality_guard(result, expected_wallet=WALLET)


def test_m315_guard_fails_on_any_exit_failure():
    rows = [_row(i, pnl=1_000_000) for i in range(10)]
    rows[4].evidence[guard.M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY]["exit_failures"] = [
        {"signature": "SELL4", "code": "EXIT_QUOTE_TOO_SLOW"}
    ]
    result = guard.build_m315_execution_reality_guard(
        wallet=WALLET,
        events=rows,
        evaluated_at=_terminal(),
    )
    assert result["passed"] is False
    assert result["checks"]["zero_technical_exit_failures"] is False


def test_m315_guard_fails_while_any_candidate_roundtrip_position_is_open():
    rows = [_row(i, pnl=1_000_000) for i in range(10)]
    rows.append(_row(10, pnl=0, status="OPEN"))
    result = guard.build_m315_execution_reality_guard(
        wallet=WALLET,
        events=rows,
        evaluated_at=_terminal(),
    )
    assert result["passed"] is False
    assert result["metrics"]["open_position_count"] == 1
    assert result["checks"]["zero_open_positions"] is False


def test_m315_guard_fails_if_best_trade_is_the_only_source_of_net_profit():
    rows = [_row(0, pnl=10_000_000)] + [_row(i + 1, pnl=-100_000) for i in range(9)]
    result = guard.build_m315_execution_reality_guard(
        wallet=WALLET,
        events=rows,
        evaluated_at=_terminal(),
    )
    assert result["metrics"]["net_pnl_lamports"] > 0
    assert result["metrics"]["net_without_best_trade_lamports"] < 0
    assert result["passed"] is False


def test_m307_future_lineage_is_fail_closed_behind_m315_guard_contract():
    assert WALLET not in m307.M307_PRE_M315_LEGACY_LINEAGE_WALLETS
    assert "2Ec7546mqCuq1PPGSWTaQZ6DdTGWhpPhEuVicJ3sTQnr" in m307.M307_PRE_M315_LEGACY_LINEAGE_WALLETS
    source = inspect.getsource(m307.build_activation_package)
    validator_source = inspect.getsource(m307.validate_activation_package)
    assert "m315_execution_reality_guard" in source
    assert "wallet not in M307_PRE_M315_LEGACY_LINEAGE_WALLETS" in source
    assert "validate_m315_execution_reality_guard" in source
    assert "m315_execution_reality_guard_required" in validator_source
    assert "validate_m315_execution_reality_guard" in validator_source
