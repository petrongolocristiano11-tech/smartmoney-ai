from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module
from backend.app.services import gen4_fastpath_shadow_service as fastpath
from backend.app.services.gen4_promoted_exit_recovery_service import (
    PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS,
    PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS,
    recover_promoted_selective_exits,
)
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.live_trading_errors import JupiterSwapError


WALLET = "CGAZ8ysbcmc6a14uYRqDJfnQvjRF4fVSZBYiTsZgRwcH"
TOKEN = "EwJi9RdHKTf6wq2qD3Z3Yn4vh42kKuMyXAZzKMKipump"


def _policy() -> dict:
    return {
        "simulated_input_lamports": 10_000_000,
        "slippage_bps": 300,
        "max_quote_latency_ms": 5_000,
        "max_price_impact_bps": 500,
        "max_price_deterioration_bps": 1_000,
        "estimated_network_fee_lamports": 100_000,
        "live_execution": False,
        "paper_execution": False,
        "automatic_live_activation": False,
    }


def _activation(now: datetime) -> CanonicalParserGen4PromotedSelectiveActivation:
    return CanonicalParserGen4PromotedSelectiveActivation(
        activation_id="a" * 36,
        wallet_address=WALLET,
        status="ACTIVE",
        activation_anchor_at=now - timedelta(hours=1),
        decision_envelope_sha256="d" * 64,
        formal_m306_report_sha256="f" * 64,
        policy_hash="p" * 64,
        policy_snapshot=_policy(),
        decision_envelope={},
        evidence={},
        draining_at=None,
        stopped_at=None,
    )


def _position(activation, now, *, remaining=1_000_000):
    return CanonicalParserGen4PromotedSelectivePosition(
        position_id="position-0000000000000000000000000001",
        scope="PROMOTED_CANDIDATE_FASTPATH_SELECTIVE",
        activation_db_id=activation.id,
        activation_id=activation.activation_id,
        entry_fast_event_id="event-000000000000000000000000000001",
        status="OPEN",
        wallet_address=WALLET,
        token_mint=TOKEN,
        token_decimals=6,
        entry_signature="entry-signature",
        entry_source="PROCESSED_WSS_PROMOTED_CANDIDATE",
        entry_received_at=now - timedelta(minutes=5),
        opened_at=now - timedelta(minutes=5),
        closed_at=None,
        entry_quote_latency_ms=100,
        entry_price_deterioration_bps=10.0,
        entry_price_impact_bps=1.0,
        entry_transaction_built=True,
        entry_input_lamports=10_000_000,
        entry_output_token_raw=1_000_000,
        remaining_token_raw=remaining,
        allocated_entry_fee_lamports=100_000,
        realized_output_lamports=0,
        allocated_exit_fee_lamports=0,
        pnl_lamports=None,
        return_percent=None,
        last_exit_signature=None,
        exit_quote_latency_ms=None,
        exit_price_impact_bps=None,
        exit_transaction_built=False,
        exit_copyable=False,
        close_reason=None,
        entry_quote={},
        exit_quotes=[],
        evidence={},
    )


class FailJupiter:
    def __init__(self, code="JUPITER_HTTP_ERROR"):
        self.code = code
        self.calls = 0

    def get_order(self, **kwargs):
        self.calls += 1
        raise JupiterSwapError(
            "No routes found",
            code=self.code,
            status_code=502,
            payload={
                "http_status": 400,
                "attempts": 1,
                "retryable": True,
                "response": {"error": "No routes found"},
            },
        )


class SuccessJupiter:
    def __init__(self):
        self.calls = 0

    def get_order(self, **kwargs):
        self.calls += 1
        amount = int(kwargs["amount_raw"])
        return JupiterOrderResult(
            raw={"otherAmountThreshold": "11800000"},
            request_id="req",
            transaction="unsigned",
            in_amount=amount,
            out_amount=12_000_000,
            slippage_bps=300,
            router="test",
            price_impact_percent=0.01,
            last_valid_block_height=None,
        )


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    CanonicalParserGen4PromotedSelectiveActivation.__table__.create(engine)
    CanonicalParserGen4PromotedSelectivePosition.__table__.create(engine)
    return engine


def test_fastpath_transient_jupiter_failure_schedules_recovery_not_terminal_failure():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=1.0,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        result = fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        evidence = dict(position.evidence or {})
        pending = dict(evidence.get("pending_exit_recovery") or {})
        assert result["reason"] == "EXIT_RECOVERY_SCHEDULED"
        assert result["autonomous_exit_recovery"]["scheduled"] is True
        assert pending["state"] == "PENDING"
        assert pending["source_signature"] == "source-sell"
        assert pending["target_remaining_token_raw"] == 0
        assert pending["initial_error"]["payload"]["http_status"] == 400
        assert list(evidence.get("exit_failures") or []) == []
        assert position.status == "OPEN"
        assert position.remaining_token_raw == 1_000_000


def test_autonomous_recovery_closes_without_new_wallet_sell():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=1.0,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        due = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
        success = SuccessJupiter()
        result = recover_promoted_selective_exits(
            db,
            jupiter_client=success,
            now=due,
        )
        assert success.calls == 1
        assert result["recovered_groups"] == 1
        assert result["positions_closed"] == 1
        assert position.status == "CLOSED"
        assert position.remaining_token_raw == 0
        assert position.exit_copyable is True
        assert position.exit_transaction_built is True
        assert position.close_reason == "MIRRORED_WALLET_EXIT_RECOVERED"
        assert position.last_exit_signature == "source-sell"
        assert dict(position.evidence)["pending_exit_recovery"]["state"] == "RECOVERED"
        assert list(dict(position.evidence).get("exit_failures") or []) == []
        assert position.exit_quotes[-1]["autonomous_exit_recovery"] is True


def test_partial_sell_recovery_only_reduces_original_requested_fraction():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-partial-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=0.5,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        due = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
        result = recover_promoted_selective_exits(
            db,
            jupiter_client=SuccessJupiter(),
            now=due,
        )
        assert result["positions_partially_reduced"] == 1
        assert position.status == "OPEN_PARTIAL"
        assert position.remaining_token_raw == 500_000
        assert dict(position.evidence)["pending_exit_recovery"]["state"] == "RECOVERED"
        assert list(dict(position.evidence).get("exit_failures") or []) == []


def test_recovery_exhaustion_becomes_one_terminal_exit_failure_and_keeps_position_open():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=1.0,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        first_due = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
        first = recover_promoted_selective_exits(
            db,
            jupiter_client=FailJupiter(),
            now=first_due,
        )
        assert first["rescheduled_groups"] == 1
        pending = dict(dict(position.evidence)["pending_exit_recovery"])
        assert pending["recovery_attempts"] == 1
        second_due = datetime.fromisoformat(pending["next_retry_at_utc"]) + timedelta(milliseconds=1)
        second = recover_promoted_selective_exits(
            db,
            jupiter_client=FailJupiter(),
            now=second_due,
        )
        failures = list(dict(position.evidence).get("exit_failures") or [])
        assert second["terminal_groups"] == 1
        assert len(failures) == 1
        assert failures[0]["code"] == "JUPITER_HTTP_ERROR"
        assert failures[0]["terminal_after_autonomous_recovery"] is True
        assert dict(position.evidence)["pending_exit_recovery"]["state"] == "TERMINAL_JUPITER_FAILURE"
        assert position.status == "OPEN"
        assert position.remaining_token_raw == 1_000_000



def test_later_sell_supersedes_pending_recovery_without_oversell():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-partial-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=0.5,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        # Simulate a later valid source-wallet SELL already reducing the same position
        # to the exact target before autonomous recovery becomes due.
        position.remaining_token_raw = 500_000
        position.status = "OPEN_PARTIAL"
        due = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
        success = SuccessJupiter()
        result = recover_promoted_selective_exits(
            db,
            jupiter_client=success,
            now=due,
        )
        assert success.calls == 0
        assert result["superseded_groups"] == 1
        assert position.remaining_token_raw == 500_000
        assert dict(position.evidence)["pending_exit_recovery"]["state"] == "SUPERSEDED_BY_LATER_EXIT"
        assert list(dict(position.evidence).get("exit_failures") or []) == []


def test_terminal_recovery_is_idempotent_and_does_not_duplicate_exit_failure():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        db.add(position)
        db.flush()
        signal = SimpleNamespace(
            signature="source-sell",
            wallet_address=WALLET,
            token_mint=TOKEN,
            sell_fraction=1.0,
        )
        event = SimpleNamespace(event_id="sell-event", fast_received_at=now)
        fastpath._apply_promoted_selective_sell_shadow(
            db,
            event=event,
            signal=signal,
            activation=activation,
            jupiter_client=FailJupiter(),
        )
        first_due = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0] + 0.1)
        recover_promoted_selective_exits(
            db,
            jupiter_client=FailJupiter(),
            now=first_due,
        )
        pending = dict(dict(position.evidence)["pending_exit_recovery"])
        second_due = datetime.fromisoformat(pending["next_retry_at_utc"]) + timedelta(milliseconds=1)
        terminal = recover_promoted_selective_exits(
            db,
            jupiter_client=FailJupiter(),
            now=second_due,
        )
        assert terminal["terminal_groups"] == 1
        failures_before = list(dict(position.evidence).get("exit_failures") or [])
        assert len(failures_before) == 1
        later = recover_promoted_selective_exits(
            db,
            jupiter_client=FailJupiter(),
            now=second_due + timedelta(seconds=30),
        )
        failures_after = list(dict(position.evidence).get("exit_failures") or [])
        assert later["due_recovery_groups"] == 0
        assert failures_after == failures_before
        assert len(failures_after) == 1

def test_historical_exit_failures_are_never_deleted_or_rewritten():
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    engine = _db()
    with Session(engine) as db:
        activation = _activation(now)
        db.add(activation)
        db.flush()
        position = _position(activation, now)
        historical = {
            "signature": "historical-sell",
            "code": "JUPITER_HTTP_ERROR",
            "observed_at": "2026-09-02T20:53:46.743216+00:00",
        }
        position.evidence = {"exit_failures": [historical]}
        db.add(position)
        db.flush()
        result = recover_promoted_selective_exits(
            db,
            jupiter_client=SuccessJupiter(),
            now=now,
        )
        assert result["due_recovery_groups"] == 0
        assert list(dict(position.evidence)["exit_failures"]) == [historical]
        assert "pending_exit_recovery" not in dict(position.evidence)


def test_runtime_wires_periodic_shadow_recovery_without_live_or_submission():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime)
    assert "_run_promoted_exit_recovery" in source
    assert "recover_promoted_selective_exits" in source
    assert "gen4-promoted-exit-recovery-shadow" in source
    status_source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime.status.fget)
    assert '"transaction_submission": False' in status_source
    assert '"live_execution": False' in status_source
    assert PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS == 2
