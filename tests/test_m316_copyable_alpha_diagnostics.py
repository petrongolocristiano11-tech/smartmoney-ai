from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import backend.app.services.gen4_fastpath_shadow_service as fastpath
import backend.app.services.gen4_m316_copyable_alpha_diagnostics_service as m316


WALLET = "GmRKk85gpi21Bti8z95fp3iWAGycAMJDz7uZKpAw1TF8"
ANCHOR = datetime(2026, 9, 12, 17, 26, 36, tzinfo=timezone.utc)


def _row(
    i: int,
    *,
    pnl: int,
    deterioration: float = 200.0,
    impact: float = 40.0,
    latency: int = 400,
    status: str = "CLOSED",
    failures=None,
):
    opened = ANCHOR + timedelta(minutes=(i * 3) + 1)
    closed = opened + timedelta(minutes=2)
    state = {
        "version": m316.M314_VERSION,
        "scope": m316.M314_SCOPE,
        "gate_armed": False,
        "strict_forward_only": True,
        "backfill": False,
        "status": status,
        "position_id": f"P{i:03d}",
        "entry_fast_event_id": f"E{i:03d}",
        "wallet_address": WALLET,
        "token_mint": f"TOKEN{i:03d}",
        "token_decimals": 6,
        "entry_signature": f"BUY{i:03d}",
        "entry_received_at": opened.isoformat(),
        "opened_at": opened.isoformat(),
        "closed_at": closed.isoformat() if status == "CLOSED" else None,
        "entry_quote_latency_ms": latency,
        "entry_price_deterioration_bps": deterioration,
        "entry_price_impact_bps": impact,
        "entry_transaction_built": True,
        "entry_input_lamports": 10_000_000,
        "entry_output_token_raw": 1_000_000,
        "remaining_token_raw": 0 if status == "CLOSED" else 1_000_000,
        "allocated_entry_fee_lamports": 100_000,
        "realized_output_lamports": 0,
        "allocated_exit_fee_lamports": 100_000 if status == "CLOSED" else 0,
        "pnl_lamports": pnl if status == "CLOSED" else None,
        "return_percent": None,
        "exit_copyable": status == "CLOSED",
        "exit_failures": list(failures or []),
    }
    return SimpleNamespace(
        event_id=f"E{i:03d}",
        wallet_address=WALLET,
        evidence={m316.M314_EVIDENCE_KEY: state},
    )


def _profitable_training_and_validation_rows():
    rows = []
    # Chronological training window: 12 low-friction winners and 6 high-friction losers.
    for i in range(18):
        if i < 12:
            pnl = 1_000_000 if i not in {4, 9} else -200_000
            rows.append(_row(i, pnl=pnl))
        else:
            rows.append(
                _row(
                    i,
                    pnl=-2_000_000,
                    deterioration=900.0,
                    impact=400.0,
                    latency=4000,
                )
            )
    # Validation window: 8 low-friction profitable trades, 4 high-friction losers.
    for i in range(18, 30):
        if i < 26:
            pnl = 1_000_000 if i != 22 else -200_000
            rows.append(_row(i, pnl=pnl))
        else:
            rows.append(
                _row(
                    i,
                    pnl=-2_000_000,
                    deterioration=900.0,
                    impact=400.0,
                    latency=4000,
                )
            )
    return rows


def test_m316_selects_on_training_and_validates_on_later_holdout_using_pre_entry_features_only():
    rows = _profitable_training_and_validation_rows()
    result = m316.build_m316_wallet_alpha_diagnostics(
        wallet=WALLET,
        events=rows,
        evaluated_at=ANCHOR + timedelta(days=1),
    )
    assert result["state"] == "VALIDATED_SHADOW_FILTER_DISARMED"
    assert result["validated_shadow_filter_pass"] is True
    assert result["shadow_filter_armed"] is False
    assert result["selected_filter"] == {
        "max_entry_price_deterioration_bps": 250.0,
        "max_entry_price_impact_bps": 50.0,
        "max_entry_quote_latency_ms": 500,
    }
    assert result["method"]["filter_selection_uses_training_outcomes_only"] is True
    assert result["method"]["validation_outcomes_never_used_to_select_filter"] is True
    assert result["method"]["trade_filter_uses_only_pre_entry_features"] is True
    assert result["evidence"]["training_filtered_metrics"]["closed_trade_count"] == 12
    assert result["evidence"]["validation_filtered_metrics"]["closed_trade_count"] == 8
    assert result["safety"]["automatic_entry_filtering"] is False


def test_m316_validation_can_veto_a_training_filter_without_arming_it():
    rows = _profitable_training_and_validation_rows()
    for row in rows[18:26]:
        row.evidence[m316.M314_EVIDENCE_KEY]["pnl_lamports"] = -1_000_000
    result = m316.build_m316_wallet_alpha_diagnostics(
        wallet=WALLET,
        events=rows,
        evaluated_at=ANCHOR + timedelta(days=1),
    )
    assert result["selected_filter"] is not None
    assert result["state"] == "TRAINING_FILTER_FOUND_VALIDATION_NOT_PASS"
    assert result["validated_shadow_filter_pass"] is False
    assert result["shadow_filter_armed"] is False


def test_m316_requires_enough_chronological_closed_evidence_before_selecting_any_filter():
    rows = [_row(i, pnl=1_000_000) for i in range(19)]
    result = m316.build_m316_wallet_alpha_diagnostics(
        wallet=WALLET,
        events=rows,
        evaluated_at=ANCHOR + timedelta(days=1),
    )
    assert result["state"] == "INSUFFICIENT_CLOSED_EVIDENCE"
    assert result["selected_filter"] is None
    assert result["validated_shadow_filter_pass"] is False


def test_m314_economic_observation_now_requires_zero_exit_failures_and_zero_open_positions():
    rows = [_row(i, pnl=1_000_000) for i in range(10)]
    clean = fastpath._candidate_roundtrip_metrics_from_events(rows)
    assert clean["economic_observation_pass"] is True
    assert clean["economic_gate"]["zero_technical_exit_failures"] is True
    assert clean["economic_gate"]["zero_open_positions"] is True
    assert "maximum_realized_equity_drawdown_percent" in clean

    rows[3].evidence[m316.M314_EVIDENCE_KEY]["exit_failures"] = [
        {"signature": "SELL003", "code": "EXIT_QUOTE_TOO_SLOW"}
    ]
    failed = fastpath._candidate_roundtrip_metrics_from_events(rows)
    assert failed["economic_observation_pass"] is False
    assert failed["economic_gate"]["zero_technical_exit_failures"] is False

    rows = [_row(i, pnl=1_000_000) for i in range(10)]
    rows.append(_row(10, pnl=0, status="OPEN"))
    opened = fastpath._candidate_roundtrip_metrics_from_events(rows)
    assert opened["economic_observation_pass"] is False
    assert opened["economic_gate"]["zero_open_positions"] is False


def test_candidate_roundtrip_status_exposes_per_wallet_and_m316_diagnostics_without_arming_filter(monkeypatch):
    rows = _profitable_training_and_validation_rows()

    class _Scalars:
        def __iter__(self):
            return iter(rows)

    class _Db:
        def scalars(self, _query):
            return _Scalars()

    monkeypatch.setattr(fastpath, "_is_candidate_event", lambda _row: True)
    status = fastpath.get_gen4_candidate_roundtrip_shadow_status(_Db(), recent_limit=5)
    assert WALLET in status["wallets"]
    assert status["m316_copyable_alpha_diagnostics"]["shadow_filter_armed"] is False
    assert status["safety"]["m316_diagnostics_observation_only"] is True
    assert status["safety"]["m316_shadow_filter_armed"] is False
