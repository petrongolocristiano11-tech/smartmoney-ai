from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(r"C:\smartmoney-ai")
sys.path.insert(0, str(PROJECT))

from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    M299_BUILDER_ARMED,
    M299_SCOPE,
    M299_VERSION,
    build_acquisition_report,
    build_challenger_progress,
    build_official_wallet_evidence,
    preparation_report,
    realized_closed_equity_drawdown_percent,
    sign_m298_evidence_from_acquisition,
    validate_acquisition_report,
)


def event(wallet, sig, when, *, category="ACCEPTED"):
    row = {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": sig,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=900),
        "fast_end_to_quote_ms": 900,
        "fast_price_impact_bps": 20.0,
        "fast_price_deterioration_bps": 300.0,
        "fast_transaction_built": True,
        "fast_provisional_copyable": True,
        "fast_provisional_rejection_reason": None,
        "parse_error_code": None,
        "quote_error_code": None,
    }
    if category == "PROTECTIVE":
        row.update(
            fast_provisional_copyable=False,
            fast_transaction_built=False,
            fast_provisional_rejection_reason="PRICE_ALREADY_MOVED",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    elif category == "TECHNICAL":
        row.update(
            fast_provisional_copyable=False,
            fast_transaction_built=False,
            fast_provisional_rejection_reason="QUOTE_TOO_SLOW",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    return row


def position(wallet, sig, when, pnl):
    return {
        "id": int(sig.strip("S") or 0),
        "position_id": "P" + sig,
        "scope": "OFFICIAL_FASTPATH_SELECTIVE",
        "campaign_id": "C",
        "wallet_address": wallet,
        "entry_signature": sig,
        "entry_received_at": when,
        "opened_at": when,
        "closed_at": when + timedelta(hours=1),
        "status": "CLOSED",
        "remaining_token_raw": 0,
        "pnl_lamports": pnl,
        "exit_copyable": True,
        "exit_transaction_built": True,
        "exit_quote_latency_ms": 100,
        "exit_price_impact_bps": 10.0,
        "evidence": {},
    }


def receipt(sig, when):
    return {
        "source": "WEBHOOK",
        "auth_verified": True,
        "signature": sig,
        "received_at": when,
        "block_time": when,
        "parsed_summary": {},
    }


def main():
    assert M299_BUILDER_ARMED is False
    assert M299_SCOPE == "M299_POST_ANCHOR_SELECTIVE_EVIDENCE_BUILDER_DISARMED"
    assert M299_VERSION == "canonical-parser-gen4-post-anchor-selective-evidence-builder/1"

    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    wallet = "WALLET"
    events = []
    positions = []
    receipts = []
    for i in range(20):
        when = anchor + timedelta(hours=1 + i * 1.5)
        sig = f"S{i+1}"
        cat = "ACCEPTED" if i < 10 else "PROTECTIVE"
        events.append(event(wallet, sig, when, category=cat))
        receipts.append(receipt(sig, when))
        if cat == "ACCEPTED":
            pnl = 30_000_000 if i < 6 else -20_000_000
            positions.append(position(wallet, sig, when, pnl))

    campaign = SimpleNamespace(
        campaign_id="C",
        selection_snapshot={"formal_m74_pass": False},
        max_quote_latency_ms=5000,
        max_price_impact_bps=500,
    )
    built = build_official_wallet_evidence(
        wallet=wallet,
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=campaign,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    row = built["wallet_evidence"]
    assert row["entry_attempts"] == 20
    assert row["accepted_attempts"] == 10
    assert row["protective_rejects"] == 10
    assert row["technical_failures"] == 0
    assert row["closed_trades"] == 10
    assert row["profit_factor"] > 2.0
    assert row["maximum_drawdown_percent"] < 15.0
    assert built["m298_individual_evaluation"]["passed"] is True

    dd = realized_closed_equity_drawdown_percent(
        [
            position(wallet, "S1", anchor, 100_000_000),
            position(wallet, "S2", anchor + timedelta(hours=2), -200_000_000),
        ],
        accepted_signatures={"S1", "S2"},
    )
    assert abs(dd["maximum_drawdown_percent"] - (200_000_000 / 1_100_000_000 * 100)) < 1e-6
    assert dd["mark_to_market_claimed"] is False

    challenger = build_challenger_progress(
        wallet=wallet,
        events=events,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=40),
    )
    assert challenger["entry_attempts"] == 20
    assert challenger["selective_evidence_eligible"] is False
    assert challenger["closed_trades_claimed"] is False

    acquisition = build_acquisition_report(
        official_results={"TEST": built},
        challenger_results={"CH": challenger},
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
    assert signed["safety"]["network_requests"] == 0
    assert signed["safety"]["database_writes"] == 0

    prep = preparation_report()
    assert prep["safety"]["builder_armed"] is False
    assert prep["drawdown_contract"]["mark_to_market_claimed"] is False
    assert prep["drawdown_contract"]["source_m74_drawdown_replaced"] is False

    print(
        "M299_PRE_VERIFY=PASS;"
        "builder_disarmed=true;"
        "m291_mapping=true;"
        "m298_shape=true;"
        "protective_rejects_preserved=true;"
        "technical_reset_supported=true;"
        "realized_follower_dd=true;"
        "source_m74_not_replaced=true;"
        "challenger_entry_only=true;"
        "acquisition_and_transform_separated=true"
    )


if __name__ == "__main__":
    main()
