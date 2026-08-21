from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.core.config import settings
from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module
from backend.app.services import gen4_fastpath_shadow_service as service


def _row(*, candidate: bool, copyable: bool = True):
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        signature=("candidate-signature" if candidate else "official-signature"),
        wallet_address=("CANDIDATE" if candidate else "OFFICIAL"),
        side="BUY",
        fast_received_at=now,
        fast_prequote_ms=15,
        fast_quote_latency_ms=500,
        fast_quote_received_at=now,
        fast_end_to_quote_ms=(None if candidate else 2000),
        fast_lead_vs_webhook_ms=(None if candidate else 3000),
        confirmed_path_end_to_quote_ms=(None if candidate else 6000),
        fast_price_deterioration_bps=(500.0 if copyable else 1500.0),
        fast_price_impact_bps=10.0,
        fast_out_amount=100,
        fast_transaction_built=True,
        fast_provisional_copyable=copyable,
        fast_provisional_rejection_reason=(None if copyable else "PRICE_ALREADY_MOVED"),
        fast_reconciled_copyable=(True if not candidate and copyable else None),
        fast_reconciled_rejection_reason=None,
        webhook_reconciled_at=(now if not candidate else None),
        parse_error_code=None,
        quote_error_code=None,
        evidence=(
            {"observation_scope": service.FASTPATH_CANDIDATE_SCOPE}
            if candidate
            else {"version": service.FASTPATH_VERSION}
        ),
    )


def test_candidate_settings_exist_and_are_disabled_by_default():
    assert hasattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WATCHLIST_ENABLED")
    assert hasattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WALLETS")
    assert hasattr(settings, "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_MAX_WALLETS")


def test_candidate_config_validator_fails_closed_when_enabled_without_wallets():
    candidate = settings.model_copy(
        update={
            "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WATCHLIST_ENABLED": True,
            "CANONICAL_PARSER_GEN4_FASTPATH_SHADOW_ENABLED": True,
            "CANONICAL_PARSER_GEN4_COPYABILITY_ENABLED": True,
            "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WALLETS": "",
        }
    )
    with pytest.raises(ValueError, match="non contiene wallet"):
        candidate.validate_gen4_fastpath_candidate_watchlist()


def test_candidate_wallet_parser_isolated_and_normalized(monkeypatch):
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WATCHLIST_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_WALLETS",
        "BBB,AAA;BBB\nCCC",
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_FASTPATH_CANDIDATE_MAX_WALLETS",
        5,
    )
    assert service.configured_fastpath_candidate_wallets() == ["AAA", "BBB", "CCC"]


def test_candidate_policy_never_weakens_m75_entry_limits(monkeypatch):
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_QUOTE_LATENCY_MS",
        120_000,
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_IMPACT_BPS",
        10_000,
    )
    monkeypatch.setattr(
        settings,
        "CANONICAL_PARSER_GEN4_COPYABILITY_MAX_PRICE_DETERIORATION_BPS",
        50_000,
    )
    policy = service._candidate_policy_snapshot()
    assert policy["max_quote_latency_ms"] == 5_000
    assert policy["max_price_impact_bps"] == 500
    assert policy["max_price_deterioration_bps"] == 1_000
    assert policy["m75_entry_caps_enforced"] is True
    assert (
        service._provisional_rejection(
            policy,
            quote_latency_ms=500,
            out_amount=100,
            transaction_built=True,
            price_impact_bps=10.0,
            deterioration_bps=1000.01,
        )
        == "PRICE_ALREADY_MOVED"
    )


def test_candidate_status_requires_20_attempts_and_never_claims_forward_pass(monkeypatch):
    monkeypatch.setattr(
        service,
        "configured_fastpath_candidate_wallets",
        lambda: ["CANDIDATE"],
    )
    rows = [_row(candidate=True, copyable=True) for _ in range(15)]
    status = service._candidate_status(rows, recent_limit=50)
    assert status["buy_count"] == 15
    assert status["entry_gate"]["attempts_met"] is False
    assert status["entry_gate"]["reject_rate_pass"] is False
    assert status["m75_forward_pass"] is False
    assert status["safety"]["campaign_created"] is False
    assert status["safety"]["positions_created"] == 0


def test_official_m117d_status_excludes_candidate_rows(monkeypatch):
    official = _row(candidate=False, copyable=True)
    candidate = _row(candidate=True, copyable=False)

    class FakeDB:
        def scalars(self, _statement):
            return [official, candidate]

    monkeypatch.setattr(service, "active_fastpath_wallets", lambda _db: ["OFFICIAL"])
    monkeypatch.setattr(
        service,
        "configured_fastpath_candidate_wallets",
        lambda: ["CANDIDATE"],
    )
    status = service.get_gen4_fastpath_shadow_status(FakeDB(), recent_limit=50)
    assert status["active_wallets"] == ["OFFICIAL"]
    assert status["event_count"] == 1
    assert status["buy_count"] == 1
    assert status["fast_provisional_copyable_count"] == 1
    assert status["candidate_watchlist"]["event_count"] == 1
    assert status["candidate_watchlist"]["buy_count"] == 1
    assert status["candidate_watchlist"]["provisional_copyable_count"] == 0
    assert status["safety"]["m117d_official_counters_include_candidate_rows"] is False


def test_runtime_uses_separate_candidate_wss_path():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime)
    assert "_run_candidate" in source
    assert "_record_candidate" in source
    assert "gen4-fastpath-candidate-shadow" in source
    assert "separate_wss_connection" in source
    official_wallet_source = inspect.getsource(
        runtime_module.EmbeddedGen4FastpathShadowRuntime._wallets
    )
    assert "active_fastpath_wallets" in official_wallet_source
    assert "configured_fastpath_candidate_wallets" not in official_wallet_source
