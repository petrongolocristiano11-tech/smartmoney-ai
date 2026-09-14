from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module
import backend.app.services.gen4_fastpath_shadow_service as service
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.live_trading_errors import JupiterSwapError


WALLET = "D7Z3ZkAjMnbvjq151vAd8xGfxA636zYz8WMb8DuvEqjd"
TOKEN = "5mHL4MEaATdQoTwLPgAbk9boaK2SUk18WEGB7okZpump"


def _policy() -> dict:
    return {
        "simulated_input_lamports": 10_000_000,
        "slippage_bps": 300,
        "max_quote_latency_ms": 5_000,
        "max_price_impact_bps": 500,
        "max_price_deterioration_bps": 1_000,
        "estimated_network_fee_lamports": 100_000,
    }


def _row(event_id: str, state: dict, *, row_id: int = 1):
    return SimpleNamespace(
        id=row_id,
        event_id=event_id,
        wallet_address=str(state.get("wallet_address") or WALLET),
        token_mint=str(state.get("token_mint") or TOKEN),
        side="BUY",
        fast_received_at=datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc),
        evidence={
            "observation_scope": service.FASTPATH_CANDIDATE_SCOPE,
            service.M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY: state,
        },
    )


def _state(*, pnl=None, status="OPEN", closed_at=None, output=1_000_000, position_id="POS1"):
    return {
        "version": service.M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": service.M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "position_id": position_id,
        "status": status,
        "wallet_address": WALLET,
        "token_mint": TOKEN,
        "token_decimals": 6,
        "entry_signature": "SIG",
        "opened_at": "2026-09-12T16:00:00+00:00",
        "closed_at": closed_at,
        "entry_input_lamports": 100_000_000,
        "entry_output_token_raw": output,
        "remaining_token_raw": 0 if status == "CLOSED" else output,
        "allocated_entry_fee_lamports": 100_000,
        "realized_output_lamports": 0,
        "allocated_exit_fee_lamports": 0,
        "pnl_lamports": pnl,
        "return_percent": None,
        "exit_copyable": status == "CLOSED",
        "exit_transaction_built": status == "CLOSED",
        "exit_quotes": [],
        "exit_failures": [],
        "policy_snapshot": _policy(),
    }


class FakeDB:
    def __init__(self, rows):
        self.rows = list(rows)

    def scalars(self, _statement):
        return list(self.rows)


class FailJupiter:
    def __init__(self, code="JUPITER_HTTP_ERROR"):
        self.code = code
        self.calls = 0

    def get_order(self, **kwargs):
        self.calls += 1
        raise JupiterSwapError(
            "temporary",
            code=self.code,
            status_code=502,
            payload={
                "http_status": 502,
                "attempts": 1,
                "retryable": True,
                "response": {"error": "temporary"},
            },
        )


class SuccessJupiter:
    def __init__(self):
        self.calls = 0

    def get_order(self, **kwargs):
        self.calls += 1
        amount = int(kwargs["amount_raw"])
        return JupiterOrderResult(
            raw={"otherAmountThreshold": "118000000"},
            request_id="req",
            transaction="unsigned",
            in_amount=amount,
            out_amount=120_000_000,
            slippage_bps=300,
            router="test",
            price_impact_percent=0.001,
            last_valid_block_height=None,
        )


def _schedule(row, now, *, fraction=1.0):
    signal = SimpleNamespace(
        signature="SELL1",
        wallet_address=WALLET,
        token_mint=TOKEN,
        sell_fraction=fraction,
    )
    event = SimpleNamespace(fast_received_at=now)
    client = FailJupiter()
    result = service._apply_candidate_roundtrip_sell_shadow(
        FakeDB([row]),
        event=event,
        signal=signal,
        policy=_policy(),
        jupiter_client=client,
    )
    return result, client


def test_m314_gate_is_disarmed_and_cannot_authorize_m307():
    assert service.M314_CANDIDATE_ROUNDTRIP_GATE_ARMED is False
    result = service._candidate_roundtrip_metrics_from_events([])
    assert result["gate_armed"] is False
    assert result["m307_authorized"] is False
    assert result["safety"]["automatic_promotion"] is False


def test_m314_metrics_require_positive_without_best_trade():
    rows = []
    base = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
    pnls = [10_000_000] + [-100_000] * 9
    for i, pnl in enumerate(pnls):
        state = _state(
            pnl=pnl,
            status="CLOSED",
            closed_at=(base + timedelta(minutes=i)).isoformat(),
            position_id=f"P{i}",
        )
        rows.append(_row(f"E{i}", state, row_id=i + 1))
    result = service._candidate_roundtrip_metrics_from_events(rows)
    assert result["closed_trade_count"] == 10
    assert result["net_pnl_lamports"] > 0
    assert result["net_without_best_trade_lamports"] < 0
    assert result["economic_observation_pass"] is False


def test_m314_metrics_can_pass_observation_without_authorizing_promotion():
    rows = []
    base = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
    pnls = [2_000_000] * 8 + [-500_000] * 2
    for i, pnl in enumerate(pnls):
        state = _state(
            pnl=pnl,
            status="CLOSED",
            closed_at=(base + timedelta(minutes=i)).isoformat(),
            position_id=f"P{i}",
        )
        rows.append(_row(f"E{i}", state, row_id=i + 1))
    result = service._candidate_roundtrip_metrics_from_events(rows)
    assert result["closed_trade_count"] == 10
    assert result["profit_factor"] >= 1.30
    assert result["net_pnl_lamports"] > 0
    assert result["net_without_best_trade_lamports"] > 0
    assert result["economic_observation_pass"] is True
    assert result["m307_authorized"] is False


def test_m314_allocation_closes_full_sell_and_computes_net_pnl():
    state = _state(output=1_000_000)
    row = _row("ENTRY1", state)
    now = datetime(2026, 9, 12, 17, tzinfo=timezone.utc)
    quote = SimpleNamespace(
        latency_ms=100,
        requested_at=now,
        received_at=now + timedelta(milliseconds=100),
        sanitized={"route":"test"},
        result=SimpleNamespace(
            price_impact_percent=0.001,
            transaction="unsigned",
            out_amount=120_000_000,
        ),
    )
    signal = SimpleNamespace(signature="SELL1", sell_fraction=1.0)
    result = service._candidate_roundtrip_apply_allocations(
        [row],
        signal=signal,
        quote=quote,
        conservative_out=120_000_000,
        amount_to_sell=1_000_000,
        fee_lamports=100_000,
    )
    updated = service._candidate_roundtrip_state(row)
    assert result == {"positions_affected":1,"positions_closed":1}
    assert updated is not None
    assert updated["status"] == "CLOSED"
    assert updated["remaining_token_raw"] == 0
    assert updated["pnl_lamports"] == 19_800_000
    assert updated["close_reason"] == "MIRRORED_WALLET_EXIT"


def test_m314_transient_jupiter_failure_schedules_recovery_without_terminal_failure():
    now = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    row = _row("ENTRY1", _state())
    result, client = _schedule(row, now)
    state = service._candidate_roundtrip_state(row)
    assert client.calls == 1
    assert result["reason"] == "EXIT_RECOVERY_SCHEDULED"
    assert result["autonomous_exit_recovery"]["scheduled"] is True
    assert state is not None
    assert state["pending_exit_recovery"]["state"] == "PENDING"
    assert state["pending_exit_recovery"]["source_signature"] == "SELL1"
    assert list(state.get("exit_failures") or []) == []
    assert state["status"] == "OPEN"


def test_m314_autonomous_recovery_closes_without_new_wallet_sell():
    now = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    row = _row("ENTRY1", _state())
    _schedule(row, now)
    due = now + timedelta(seconds=service.M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
    success = SuccessJupiter()
    result = service._recover_candidate_roundtrip_rows(
        [row], jupiter_client=success, now=due
    )
    state = service._candidate_roundtrip_state(row)
    assert success.calls == 1
    assert result["recovered_groups"] == 1
    assert result["positions_closed"] == 1
    assert state is not None
    assert state["status"] == "CLOSED"
    assert state["remaining_token_raw"] == 0
    assert state["close_reason"] == "MIRRORED_WALLET_EXIT_RECOVERED"
    assert state["pending_exit_recovery"]["state"] == "RECOVERED"
    assert list(state.get("exit_failures") or []) == []
    assert state["exit_quotes"][-1]["autonomous_exit_recovery"] is True


def test_m314_recovery_exhaustion_becomes_one_terminal_failure():
    now = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    row = _row("ENTRY1", _state())
    _schedule(row, now)
    first_due = now + timedelta(seconds=service.M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
    first = service._recover_candidate_roundtrip_rows(
        [row], jupiter_client=FailJupiter(), now=first_due
    )
    assert first["rescheduled_groups"] == 1
    state = service._candidate_roundtrip_state(row)
    assert state is not None
    pending = dict(state["pending_exit_recovery"])
    assert pending["recovery_attempts"] == 1
    second_due = datetime.fromisoformat(pending["next_retry_at_utc"]) + timedelta(milliseconds=1)
    second = service._recover_candidate_roundtrip_rows(
        [row], jupiter_client=FailJupiter(), now=second_due
    )
    state = service._candidate_roundtrip_state(row)
    assert state is not None
    failures = list(state.get("exit_failures") or [])
    assert second["terminal_groups"] == 1
    assert len(failures) == 1
    assert failures[0]["code"] == "JUPITER_HTTP_ERROR"
    assert failures[0]["terminal_after_autonomous_recovery"] is True
    assert state["pending_exit_recovery"]["state"] == "TERMINAL_JUPITER_FAILURE"
    assert state["status"] == "OPEN"


def test_m314_later_exit_supersedes_pending_recovery_without_oversell():
    now = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
    row = _row("ENTRY1", _state())
    _schedule(row, now, fraction=0.5)
    state = service._candidate_roundtrip_state(row)
    assert state is not None
    state["remaining_token_raw"] = 500_000
    state["status"] = "OPEN_PARTIAL"
    service._set_candidate_roundtrip_state(row, state)
    due = now + timedelta(seconds=service.M314_CANDIDATE_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
    success = SuccessJupiter()
    result = service._recover_candidate_roundtrip_rows(
        [row], jupiter_client=success, now=due
    )
    state = service._candidate_roundtrip_state(row)
    assert success.calls == 0
    assert result["superseded_groups"] == 1
    assert state is not None
    assert state["remaining_token_raw"] == 500_000
    assert state["pending_exit_recovery"]["state"] == "SUPERSEDED_BY_LATER_EXIT"
    assert list(state.get("exit_failures") or []) == []


def test_m314_historical_exit_failure_is_never_rewritten_or_recovered():
    historical = {
        "signature": "historical",
        "code": "JUPITER_HTTP_ERROR",
        "observed_at": "2026-09-13T20:55:46+00:00",
    }
    state = _state()
    state["exit_failures"] = [historical]
    row = _row("ENTRY1", state)
    result = service._recover_candidate_roundtrip_rows(
        [row],
        jupiter_client=SuccessJupiter(),
        now=datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc),
    )
    updated = service._candidate_roundtrip_state(row)
    assert result["due_recovery_groups"] == 0
    assert updated is not None
    assert list(updated["exit_failures"]) == [historical]
    assert "pending_exit_recovery" not in updated


def test_m314_runtime_wires_periodic_candidate_recovery_without_live_or_submission():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime)
    assert "_run_candidate_exit_recovery" in source
    assert "recover_candidate_roundtrip_exits" in source
    assert "gen4-m314-candidate-exit-recovery-shadow" in source
    status_source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime.status.fget)
    assert '"candidate_exit_recovery"' in status_source
    assert '"transaction_submission": False' in status_source
    assert '"live_execution": False' in status_source
    assert service.M314_CANDIDATE_EXIT_RECOVERY_MAX_ATTEMPTS == 2


def test_candidate_recorder_keeps_m300_sell_semantics_and_adds_m314_capture():
    source = inspect.getsource(service.record_fastpath_candidate_notification)
    assert 'event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"' in source
    assert "_apply_candidate_roundtrip_sell_shadow" in source
    assert "sell_fraction" in source
    assert "M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY" in source
