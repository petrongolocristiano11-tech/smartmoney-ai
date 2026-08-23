from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4FastpathSelectivePosition,
)
from backend.app.services import gen4_fastpath_shadow_service as service
from backend.app.services.jupiter_swap_client import JupiterOrderResult


def _position(*, pnl: int | None = None, status: str = "OPEN", idx: int = 1):
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
    return CanonicalParserGen4FastpathSelectivePosition(
        id=idx,
        position_id=f"position-{idx}",
        scope=service.FASTPATH_SELECTIVE_SCOPE,
        campaign_id="campaign",
        entry_fast_event_id=f"event-{idx}",
        status=status,
        wallet_address="WALLET",
        token_mint="TOKEN",
        token_decimals=6,
        entry_signature=f"entry-{idx}",
        entry_source=service.FASTPATH_SELECTIVE_ENTRY_SOURCE,
        entry_received_at=now,
        opened_at=now,
        closed_at=(now + timedelta(minutes=idx) if status == "CLOSED" else None),
        entry_quote_latency_ms=100,
        entry_price_deterioration_bps=100.0,
        entry_price_impact_bps=1.0,
        entry_transaction_built=True,
        entry_input_lamports=10_000_000,
        entry_output_token_raw=1_000_000,
        remaining_token_raw=(0 if status == "CLOSED" else 1_000_000),
        allocated_entry_fee_lamports=100_000,
        realized_output_lamports=(10_100_000 + (pnl or 0) if status == "CLOSED" else 0),
        allocated_exit_fee_lamports=0,
        pnl_lamports=pnl,
        return_percent=None,
        last_exit_signature=(f"exit-{idx}" if status == "CLOSED" else None),
        exit_quote_latency_ms=(100 if status == "CLOSED" else None),
        exit_price_impact_bps=(1.0 if status == "CLOSED" else None),
        exit_transaction_built=(status == "CLOSED"),
        exit_copyable=(status == "CLOSED"),
        close_reason=("MIRRORED_WALLET_EXIT" if status == "CLOSED" else None),
        entry_quote={},
        exit_quotes=[],
        evidence={"version": service.FASTPATH_SELECTIVE_POSITION_VERSION},
    )


def test_selective_table_is_dedicated_and_has_no_copyability_position_fk():
    table = CanonicalParserGen4FastpathSelectivePosition.__table__
    assert table.name == "canonical_parser_gen4_fastpath_selective_positions"
    assert not table.foreign_keys
    assert "campaign_id" in table.c
    assert "entry_fast_event_id" in table.c


def test_selective_economic_gate_requires_robust_positive_subset():
    rows = [_position(pnl=1_000_000, status="CLOSED", idx=i + 1) for i in range(10)]
    metrics = service._selective_wallet_metrics(rows)
    assert metrics["closed_trade_count"] == 10
    assert metrics["net_pnl_lamports"] == 10_000_000
    assert metrics["profit_factor"] == 999.0
    assert metrics["economic_gate"]["candidate_pass"] is True


def test_selective_economic_gate_fails_when_best_trade_is_required_for_profit():
    pnls = [10_000_000] + [-900_000] * 9
    rows = [_position(pnl=value, status="CLOSED", idx=i + 1) for i, value in enumerate(pnls)]
    metrics = service._selective_wallet_metrics(rows)
    assert metrics["net_pnl_lamports"] > 0
    assert metrics["net_without_best_trade_lamports"] < 0
    assert metrics["economic_gate"]["candidate_pass"] is False


def test_selective_exit_partial_then_close_uses_conservative_lifecycle(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    CanonicalParserGen4FastpathSelectivePosition.__table__.create(engine)
    now = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)

    class FakeClient:
        def get_order(self, **kwargs):
            amount = int(kwargs["amount_raw"])
            return JupiterOrderResult(
                raw={},
                request_id="req",
                transaction="unsigned",
                in_amount=amount,
                out_amount=12_000_000,
                slippage_bps=300,
                router="test",
                price_impact_percent=0.01,
                last_valid_block_height=None,
            )

    campaign = SimpleNamespace(
        campaign_id="campaign",
        slippage_bps=300,
        estimated_network_fee_lamports=100_000,
        max_quote_latency_ms=5_000,
        max_price_impact_bps=500,
    )
    event = SimpleNamespace(event_id="sell-event", fast_received_at=now)

    with Session(engine) as db:
        db.add(_position(idx=1))
        db.flush()
        signal = SimpleNamespace(
            signature="sell-1",
            wallet_address="WALLET",
            token_mint="TOKEN",
            sell_fraction=0.5,
        )
        first = service._apply_selective_sell_shadow(
            db, event=event, signal=signal, campaign=campaign, jupiter_client=FakeClient()
        )
        row = db.query(CanonicalParserGen4FastpathSelectivePosition).one()
        assert first["exit_applied"] is True
        assert row.status == service.FASTPATH_SELECTIVE_POSITION_OPEN_PARTIAL
        assert row.remaining_token_raw == 500_000
        signal.sell_fraction = 1.0
        signal.signature = "sell-2"
        second = service._apply_selective_sell_shadow(
            db, event=event, signal=signal, campaign=campaign, jupiter_client=FakeClient()
        )
        assert second["positions_closed"] == 1
        assert row.status == service.FASTPATH_SELECTIVE_POSITION_CLOSED
        assert row.pnl_lamports is not None
        assert row.exit_copyable is True



def test_wallet_hint_preserves_official_wallet_ordering_key():
    wallet = "Wallet1111111111111111111111111111111111"
    message = {
        "params": {
            "result": {
                "signature": "sig",
                "slot": 1,
                "transaction": {
                    "meta": {
                        "preTokenBalances": [{"owner": wallet}],
                        "postTokenBalances": [],
                    },
                    "transaction": {
                        "signatures": ["sig"],
                        "message": {"accountKeys": []},
                    },
                },
            }
        }
    }
    assert service.fastpath_notification_wallet_hint(message, [wallet, "OTHER"]) == wallet


def test_official_runtime_serializes_same_wallet_without_global_serialization():
    from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module

    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._handle)
    assert "_official_wallet_locks" in source
    assert "async with lock" in source
    assert "async with semaphore" in source
    assert source.index("async with lock") < source.index("async with semaphore")


def test_candidate_path_remains_position_isolated():
    source = inspect.getsource(service.record_fastpath_candidate_notification)
    assert "_new_selective_position" not in source
    assert "_apply_selective_sell_shadow" not in source
    assert "CanonicalParserGen4FastpathSelectivePosition" not in source


def test_selective_status_never_claims_m75_or_live():
    class FakeDB:
        def scalars(self, _statement):
            return []

    status = service._selective_position_status(FakeDB(), official_events=[], recent_limit=50)
    assert status["position_count"] == 0
    assert status["safety"]["m75_forward_pass"] is False
    assert status["safety"]["live_execution"] is False
    assert status["safety"]["signer_access"] is False
    assert status["safety"]["copyability_position_rows_created"] == 0
    assert status["safety"]["m75_thresholds_changed"] is False
    assert status["safety"]["reject_limit_changed"] is False
