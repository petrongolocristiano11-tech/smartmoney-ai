from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    build_acquisition_report,
    build_challenger_progress,
    build_official_wallet_evidence,
    realized_closed_equity_drawdown_percent,
    sign_m298_evidence_from_acquisition,
    validate_acquisition_report,
)


def _event(wallet, sig, when, kind="ACCEPTED"):
    x = {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": sig,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=800),
        "fast_end_to_quote_ms": 800,
        "fast_price_impact_bps": 15.0,
        "fast_price_deterioration_bps": 250.0,
        "fast_transaction_built": True,
        "fast_provisional_copyable": True,
        "fast_provisional_rejection_reason": None,
        "parse_error_code": None,
        "quote_error_code": None,
    }
    if kind == "PROTECTIVE":
        x.update(
            fast_provisional_copyable=False,
            fast_transaction_built=False,
            fast_provisional_rejection_reason="PRICE_ALREADY_MOVED",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    if kind == "TECHNICAL":
        x.update(
            fast_provisional_copyable=False,
            fast_transaction_built=False,
            fast_provisional_rejection_reason="QUOTE_TOO_SLOW",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    return x


def _position(wallet, sig, when, pnl):
    return {
        "id": 1,
        "position_id": "P-" + sig,
        "scope": "OFFICIAL_FASTPATH_SELECTIVE",
        "campaign_id": "C",
        "wallet_address": wallet,
        "entry_signature": sig,
        "entry_received_at": when,
        "opened_at": when,
        "closed_at": when + timedelta(minutes=30),
        "status": "CLOSED",
        "remaining_token_raw": 0,
        "pnl_lamports": pnl,
        "exit_copyable": True,
        "exit_transaction_built": True,
        "exit_quote_latency_ms": 100,
        "exit_price_impact_bps": 5.0,
        "evidence": {},
    }


def _receipt(sig, when):
    return {
        "source": "WEBHOOK",
        "auth_verified": True,
        "signature": sig,
        "received_at": when,
        "block_time": when,
        "parsed_summary": {},
    }


def _campaign():
    return SimpleNamespace(
        campaign_id="C",
        selection_snapshot={"formal_m74_pass": False},
        max_quote_latency_ms=5000,
        max_price_impact_bps=500,
    )


def _strong_dataset(anchor, wallet="W"):
    events, positions, receipts = [], [], []
    for i in range(20):
        when = anchor + timedelta(hours=1 + i * 1.5)
        sig = f"S{i}"
        kind = "ACCEPTED" if i < 10 else "PROTECTIVE"
        events.append(_event(wallet, sig, when, kind))
        receipts.append(_receipt(sig, when))
        if kind == "ACCEPTED":
            pnl = 30_000_000 if i < 6 else -20_000_000
            positions.append(_position(wallet, sig, when, pnl))
    return events, positions, receipts


def test_fifty_percent_protective_reject_maps_to_m298_and_can_pass():
    anchor = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
    events, positions, receipts = _strong_dataset(anchor)
    out = build_official_wallet_evidence(
        wallet="W",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    row = out["wallet_evidence"]
    assert row["entry_attempts"] == 20
    assert row["accepted_attempts"] == 10
    assert row["protective_rejects"] == 10
    assert out["m298_individual_evaluation"]["passed"] is True


def test_technical_failure_resets_effective_clean_window():
    anchor = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
    events = [_event("W", "OLD", anchor + timedelta(hours=1), "ACCEPTED")]
    positions = [_position("W", "OLD", anchor + timedelta(hours=1), 500_000_000)]
    receipts = [_receipt("OLD", anchor + timedelta(hours=1))]
    fail_at = anchor + timedelta(hours=2)
    events.append(_event("W", "FAIL", fail_at, "TECHNICAL"))
    receipts.append(_receipt("FAIL", fail_at))

    for i in range(20):
        when = anchor + timedelta(hours=3 + i * 1.5)
        sig = f"N{i}"
        kind = "ACCEPTED" if i < 10 else "PROTECTIVE"
        events.append(_event("W", sig, when, kind))
        receipts.append(_receipt(sig, when))
        if kind == "ACCEPTED":
            positions.append(_position("W", sig, when, 20_000_000 if i < 7 else -10_000_000))

    out = build_official_wallet_evidence(
        wallet="W",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    row = out["wallet_evidence"]
    assert row["m299_metadata"]["technical_reset_applied"] is True
    assert row["entry_attempts"] == 20
    assert row["accepted_attempts"] == 10
    assert row["technical_failures"] == 0
    assert row["net_pnl_sol"] < 0.5


def test_realized_drawdown_is_separate_from_source_mtm():
    anchor = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
    dd = realized_closed_equity_drawdown_percent(
        [
            _position("W", "A", anchor, 100_000_000),
            _position("W", "B", anchor + timedelta(hours=1), -200_000_000),
        ],
        accepted_signatures={"A", "B"},
    )
    expected = 200_000_000 / 1_100_000_000 * 100
    assert abs(dd["maximum_drawdown_percent"] - expected) < 1e-6
    assert dd["mark_to_market_claimed"] is False
    assert dd["source_m74_drawdown_replaced"] is False


def test_challenger_never_invents_full_lifecycle():
    anchor = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
    events, _, _ = _strong_dataset(anchor)
    out = build_challenger_progress(
        wallet="W",
        events=events,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    assert out["selective_evidence_eligible"] is False
    assert out["full_lifecycle_claimed"] is False
    assert out["closed_trades_claimed"] is False
    assert out["profit_factor_claimed"] is False
    assert out["drawdown_claimed"] is False


def test_acquisition_provenance_is_networked_readonly_but_transform_is_zero_network():
    anchor = datetime(2026, 8, 31, 12, 30, tzinfo=timezone.utc)
    events, positions, receipts = _strong_dataset(anchor)
    official = build_official_wallet_evidence(
        wallet="W",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    acquisition = build_acquisition_report(
        official_results={"W": official},
        challenger_results={},
        acquired_at=anchor + timedelta(hours=40),
        acquisition_safety={
            "database_transaction": "REPEATABLE_READ_READ_ONLY",
            "database_select_statements": 5,
            "database_writes": 0,
            "railway_cli_reads": 2,
            "network_accessed_for_readonly_acquisition": True,
            "backend_mutations": 0,
            "helius_calls": 0,
            "helius_credits": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "live": False,
            "signer": False,
            "paper_orders": 0,
        },
    )
    validate_acquisition_report(acquisition)
    signed = sign_m298_evidence_from_acquisition(acquisition)
    assert signed["lineage"]["m299_acquisition_was_networked_read_only"] is True
    assert signed["lineage"]["m299_transform_network_requests"] == 0
    assert signed["safety"]["network_requests"] == 0
    assert signed["safety"]["database_writes"] == 0
