from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services import gen4_fastpath_shadow_service as service


def _row(
    *,
    signature: str,
    wallet: str,
    at: datetime,
    candidate: bool,
    side: str = "BUY",
    copyable: bool = True,
    rejection: str | None = None,
    prequote_ms: int | None = 100,
    quote_latency_ms: int | None = 400,
    end_to_quote_ms: int | None = None,
    deterioration_bps: float | None = 250.0,
    impact_bps: float | None = 25.0,
    parse_error: str | None = None,
    quote_error: str | None = None,
):
    return SimpleNamespace(
        signature=signature,
        wallet_address=wallet,
        side=side,
        fast_received_at=at,
        fast_prequote_ms=prequote_ms,
        fast_quote_latency_ms=quote_latency_ms,
        fast_quote_received_at=(at if quote_latency_ms is not None else None),
        fast_end_to_quote_ms=end_to_quote_ms,
        fast_price_deterioration_bps=deterioration_bps,
        fast_price_impact_bps=impact_bps,
        fast_transaction_built=bool(copyable or rejection),
        fast_provisional_copyable=copyable,
        fast_provisional_rejection_reason=rejection,
        parse_error_code=parse_error,
        quote_error_code=quote_error,
        evidence=(
            {"observation_scope": service.FASTPATH_CANDIDATE_SCOPE}
            if candidate
            else {"version": service.FASTPATH_VERSION}
        ),
    )


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self, _statement):
        # The service also applies exact Python-side wallet/anchor/scope filters,
        # which keeps the contract testable independently of a SQL engine.
        return list(self.rows)


def test_persistent_forward_status_is_anchor_and_wallet_exact():
    anchor = datetime(2026, 8, 23, 19, 26, 27, tzinfo=timezone.utc)
    wallet = "2YF4WdLM6s2yKUCarrtBCB1jbjxeHUjoghPrJShDaqvW"
    rows = [
        _row(
            signature="pre-anchor",
            wallet=wallet,
            at=anchor - timedelta(seconds=1),
            candidate=True,
        ),
        _row(
            signature="accepted",
            wallet=wallet,
            at=anchor + timedelta(seconds=1),
            candidate=True,
            copyable=True,
            prequote_ms=125,
            quote_latency_ms=375,
            deterioration_bps=350.0,
        ),
        _row(
            signature="pam-rejected",
            wallet=wallet,
            at=anchor + timedelta(seconds=2),
            candidate=True,
            copyable=False,
            rejection="PRICE_ALREADY_MOVED",
            prequote_ms=200,
            quote_latency_ms=800,
            deterioration_bps=1400.0,
        ),
        _row(
            signature="other-wallet",
            wallet="43reoQjz67rzbUvmVomhVoMVyPKzrFrBs4cn3s4Kb8Kx",
            at=anchor + timedelta(seconds=3),
            candidate=True,
        ),
        _row(
            signature="same-wallet-official",
            wallet=wallet,
            at=anchor + timedelta(seconds=4),
            candidate=False,
        ),
    ]

    status = service.get_gen4_fastpath_forward_wallet_status(
        FakeDB(rows),
        wallet_address=wallet,
        anchor_utc=anchor,
        scope="CANDIDATE",
        recent_limit=50,
    )

    assert status["persistent_db_evidence"] is True
    assert status["window_limited"] is False
    assert status["event_count"] == 2
    assert status["buy_count"] == 2
    assert status["accepted_buy_count"] == 1
    assert status["rejected_buy_count"] == 1
    assert status["entry_acceptance_rate_percent"] == 50.0
    assert status["entry_reject_rate_percent"] == 50.0
    assert status["pam_rejection_count"] == 1
    assert status["pam_rejection_rate_percent"] == 50.0
    assert status["rejection_breakdown"] == {"PRICE_ALREADY_MOVED": 1}
    assert status["fast_received_to_quote_ms"]["p50"] == 750.0
    assert status["fast_received_to_quote_ms"]["p95"] == 975.0
    assert status["entry_gate"]["attempts_met"] is False
    assert status["entry_gate"]["reject_rate_pass"] is False
    assert status["m75_forward_pass"] is False
    assert status["safety"]["helius_credits"] == 0
    assert status["safety"]["birdeye_cu"] == 0


def test_zero_buy_status_uses_null_rates_not_false_100_percent():
    anchor = datetime(2026, 8, 23, 19, 26, 27, tzinfo=timezone.utc)
    wallet = "2YF4WdLM6s2yKUCarrtBCB1jbjxeHUjoghPrJShDaqvW"

    status = service.get_gen4_fastpath_forward_wallet_status(
        FakeDB([]),
        wallet_address=wallet,
        anchor_utc=anchor,
        scope="CANDIDATE",
        recent_limit=50,
    )

    assert status["buy_count"] == 0
    assert status["entry_acceptance_rate_percent"] is None
    assert status["entry_reject_rate_percent"] is None
    assert status["pam_rejection_rate_percent"] is None
    assert status["entry_gate"]["attempts_met"] is False
    assert status["entry_gate"]["reject_rate_pass"] is False


def test_persistent_counts_are_not_limited_by_recent_output_window():
    anchor = datetime(2026, 8, 23, 19, 26, 27, tzinfo=timezone.utc)
    wallet = "2YF4WdLM6s2yKUCarrtBCB1jbjxeHUjoghPrJShDaqvW"
    rows = [
        _row(
            signature=f"sig-{index:04d}",
            wallet=wallet,
            at=anchor + timedelta(seconds=index + 1),
            candidate=True,
            copyable=(index % 5 != 0),
            rejection=("PRICE_ALREADY_MOVED" if index % 5 == 0 else None),
        )
        for index in range(600)
    ]

    status = service.get_gen4_fastpath_forward_wallet_status(
        FakeDB(rows),
        wallet_address=wallet,
        anchor_utc=anchor,
        scope="CANDIDATE",
        recent_limit=5,
    )

    assert status["event_count"] == 600
    assert status["buy_count"] == 600
    assert status["accepted_buy_count"] == 480
    assert status["rejected_buy_count"] == 120
    assert status["entry_reject_rate_percent"] == 20.0
    assert status["entry_gate"]["attempts_met"] is True
    assert status["entry_gate"]["reject_rate_pass"] is True
    assert len(status["recent"]) == 5
    assert status["recent"][0]["signature"] == "sig-0599"


def test_official_scope_excludes_candidate_rows():
    anchor = datetime(2026, 8, 23, 19, 26, 27, tzinfo=timezone.utc)
    wallet = "Q4J6vefnKFmg5gAxGwnhthk5sewKDpnC8YNLD7Lv9ng"
    rows = [
        _row(
            signature="candidate",
            wallet=wallet,
            at=anchor + timedelta(seconds=1),
            candidate=True,
        ),
        _row(
            signature="official",
            wallet=wallet,
            at=anchor + timedelta(seconds=2),
            candidate=False,
            end_to_quote_ms=1700,
        ),
    ]

    status = service.get_gen4_fastpath_forward_wallet_status(
        FakeDB(rows),
        wallet_address=wallet,
        anchor_utc=anchor,
        scope="OFFICIAL",
        recent_limit=50,
    )

    assert status["event_count"] == 1
    assert status["recent"][0]["signature"] == "official"
    assert status["fast_received_to_quote_ms"]["p50"] == 1700.0


def test_m169_openapi_read_only_route_present():
    from backend.app.main import app

    app.openapi_schema = None
    schema = app.openapi()
    path = "/integrity/parser-gen4-fastpath-shadow/forward-wallet-status"
    assert path in schema["paths"]
    assert set(schema["paths"][path]) == {"get"}
    operation = schema["paths"][path]["get"]
    parameter_names = {item["name"] for item in operation["parameters"]}
    assert {"wallet_address", "anchor_utc", "scope", "recent_limit"}.issubset(parameter_names)
