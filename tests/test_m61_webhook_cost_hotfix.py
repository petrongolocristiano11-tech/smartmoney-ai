from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityCampaign,
    CanonicalParserGen4WebhookReceipt,
)
from backend.app.models.gen4_forward_feed import CanonicalParserGen4ForwardFeedState
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.services import blockchain_parser_gen4_forward_feed_service as feed_service
from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
    GEN4_FORWARD_FEED_POLL_CONFIRMATION,
    get_gen4_forward_feed_status,
    run_gen4_forward_feed_poll,
)

NOW = datetime(2026, 8, 8, 0, 0, 0, tzinfo=timezone.utc)
PRIMARY_A = "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE"
PRIMARY_B = "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S"
CANDIDATE = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
PRIMARY_COPY_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
WEBHOOK_ID = "6fde5163-5687-48df-a191-948adb8fa2c4"


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def feed_settings(monkeypatch):
    values = {
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED": True,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART": True,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS": 120,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_MAX_REQUESTS_PER_RUN": 4,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_PAGE_SIZE": 100,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_OVERLAP_SECONDS": 90,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_LEASE_SECONDS": 180,
        "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP": 2000,
        "CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS": 300,
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED": True,
    }
    for key, value in values.items():
        monkeypatch.setattr(feed_service.settings, key, value)


def make_forward(db: Session) -> CanonicalParserGen4ForwardCampaign:
    anchor = NOW - timedelta(days=4)
    row = CanonicalParserGen4ForwardCampaign(
        campaign_id=str(uuid4()),
        campaign_key="a" * 64,
        scope="GEN4_STRICT_FORWARD_SHADOW",
        status="ACTIVE",
        verdict="COLLECTING",
        strict_evidence_status="COLLECTING",
        policy_version="canonical-parser-gen4-strict-forward-shadow/1",
        policy_hash="b" * 64,
        policy_snapshot={},
        frozen_wallets=[PRIMARY_A, PRIMARY_B],
        frozen_wallet_metrics={},
        frozen_wallet_count=2,
        anchor_at=anchor,
        minimum_complete_at=anchor + timedelta(days=21),
        latest_observed_at=NOW - timedelta(seconds=30),
        started_at=anchor,
        completed_at=None,
        minimum_observation_days=21,
        minimum_closed_trades=30,
        proof_closed_trades=100,
        cycle_count=0,
        decision_count=0,
        strict_signal_count=0,
        proxy_signal_count=0,
        baseline_signal_count=0,
        strict_closed_trade_count=0,
        proxy_closed_trade_count=0,
        baseline_closed_trade_count=0,
        rejected_decision_count=0,
        strict_metrics={},
        proxy_metrics={},
        baseline_metrics={},
        evidence_gaps=[],
        safety={},
        evidence_hash="c" * 64,
        actor_label="TEST",
        note=None,
        technical_metadata={},
    )
    db.add(row)
    db.flush()
    return row


def make_copyability(
    db: Session,
    forward: CanonicalParserGen4ForwardCampaign,
    *,
    role: str,
    wallets: list[str],
    campaign_id: str | None = None,
) -> CanonicalParserGen4CopyabilityCampaign:
    anchor = NOW - timedelta(days=4)
    row = CanonicalParserGen4CopyabilityCampaign(
        campaign_id=campaign_id or str(uuid4()),
        forward_campaign_db_id=forward.id,
        status="ACTIVE",
        campaign_role=role,
        candidate_key=(("p" * 64) if role == "PRIMARY_FORWARD" else ("q" * 64)),
        verdict="COLLECTING",
        policy_version="canonical-parser-gen4-copyability/1",
        policy_hash="d" * 64,
        policy_snapshot={},
        frozen_wallets=wallets,
        selection_snapshot={},
        anchor_at=anchor,
        minimum_complete_at=anchor + timedelta(days=21),
        latest_observed_at=NOW - timedelta(seconds=30),
        started_at=anchor,
        completed_at=None,
        minimum_observation_days=21,
        minimum_closed_trades=30,
        proof_closed_trades=100,
        simulated_input_lamports=10_000_000,
        slippage_bps=300,
        max_signal_age_ms=20_000,
        max_quote_latency_ms=5_000,
        max_price_impact_bps=500,
        max_price_deterioration_bps=1_000,
        estimated_network_fee_lamports=100_000,
        minimum_webhook_coverage_percent=95.0,
        minimum_profit_factor=1.2,
        maximum_drawdown_percent=20.0,
        webhook_id=WEBHOOK_ID,
        webhook_status="ACTIVE",
        webhook_url="https://backend.test/integrity/parser-gen4-copyability/webhook/helius",
        webhook_configured_at=anchor,
        last_webhook_at=None,
        metrics={},
        evidence_gaps=[],
        safety={},
        actor_label="TEST",
        note=None,
        technical_metadata={},
    )
    db.add(row)
    db.flush()
    return row


def make_receipt(
    db: Session,
    campaign: CanonicalParserGen4CopyabilityCampaign,
    wallet: str,
    *,
    received_at: datetime,
) -> None:
    row = CanonicalParserGen4WebhookReceipt(
        receipt_id=str(uuid4()),
        campaign_db_id=campaign.id,
        signature=str(uuid4()),
        event_hash="e" * 64,
        source="WEBHOOK",
        status="PROCESSED",
        auth_verified=True,
        wallet_address=wallet,
        matched_wallets=[wallet],
        slot=123,
        block_time=received_at,
        received_at=received_at,
        first_received_at=received_at,
        last_received_at=received_at,
        processing_started_at=received_at,
        processed_at=received_at,
        delivery_count=1,
        processing_attempts=1,
        error_code=None,
        error_message=None,
        raw_payload={},
        parsed_summary={},
    )
    db.add(row)
    db.flush()


def fake_cycle(campaign_id: str):
    return {
        "cycle": {
            "cycle_id": str(uuid4()),
            "sequence": 1,
            "status": "COMPLETED",
            "new_decision_count": 0,
            "updated_decision_count": 0,
        },
        "campaign": {"campaign_id": campaign_id},
    }


def prepare(db: Session):
    forward = make_forward(db)
    primary = make_copyability(
        db,
        forward,
        role="PRIMARY_FORWARD",
        wallets=[PRIMARY_A, PRIMARY_B],
        campaign_id=PRIMARY_COPY_ID,
    )
    get_gen4_forward_feed_status(db)
    state = db.query(CanonicalParserGen4ForwardFeedState).one()
    state.feed_started_at = NOW - timedelta(hours=1)
    state.last_success_at = NOW - timedelta(seconds=120)
    db.commit()
    return forward, primary, state


def test_idle_primary_webhook_gate_uses_zero_history_requests(db: Session, monkeypatch):
    forward, _primary, _state = prepare(db)

    def forbidden_history(*_args, **_kwargs):
        raise AssertionError("idle webhook gate must not call Helius history")

    monkeypatch.setattr(feed_service, "get_wallet_history", forbidden_history)
    monkeypatch.setattr(
        feed_service,
        "run_gen4_forward_cycle",
        lambda *_args, **_kwargs: fake_cycle(forward.campaign_id),
    )

    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=forward.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    db.commit()

    run = result["run"]
    assert run["status"] == "NOOP"
    assert run["helius_requests"] == 0
    assert run["details"]["acquisition_mode"] == "WEBHOOK_GATED_RECOVERY"
    assert run["details"]["provider_call_skipped"] is True
    assert run["details"]["triggered_wallet_count"] == 0
    status = result["status"]
    assert status["state"]["total_helius_requests"] == 0


def test_fresh_primary_webhook_receipt_polls_only_triggered_wallet(db: Session, monkeypatch):
    forward, primary, _state = prepare(db)
    make_receipt(db, primary, PRIMARY_A, received_at=NOW - timedelta(seconds=10))
    db.commit()

    calls: list[str] = []

    def fake_history(address: str, **_kwargs):
        calls.append(address)
        return []

    monkeypatch.setattr(feed_service, "get_wallet_history", fake_history)
    monkeypatch.setattr(
        feed_service,
        "save_wallet_history_transactions",
        lambda *_args, **_kwargs: {
            "transactions_found": 0,
            "swaps_found": 0,
            "trades_imported": 0,
            "trades_updated": 0,
            "parse_failures": 0,
        },
    )
    monkeypatch.setattr(
        feed_service,
        "run_gen4_forward_cycle",
        lambda *_args, **_kwargs: fake_cycle(forward.campaign_id),
    )

    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=forward.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    db.commit()

    assert calls == [PRIMARY_A]
    assert result["run"]["helius_requests"] == 1
    assert result["run"]["wallet_count"] == 1
    assert result["run"]["details"]["triggered_wallets"] == [PRIMARY_A]
    assert result["run"]["details"]["provider_call_skipped"] is False


def test_candidate_receipt_does_not_trigger_primary_forward_feed(db: Session, monkeypatch):
    forward, _primary, _state = prepare(db)
    candidate = make_copyability(
        db,
        forward,
        role="QUALIFIED_CANDIDATE",
        wallets=[CANDIDATE],
    )
    make_receipt(db, candidate, CANDIDATE, received_at=NOW - timedelta(seconds=5))
    db.commit()

    monkeypatch.setattr(
        feed_service,
        "get_wallet_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("candidate receipt must not trigger primary feed")
        ),
    )
    monkeypatch.setattr(
        feed_service,
        "run_gen4_forward_cycle",
        lambda *_args, **_kwargs: fake_cycle(forward.campaign_id),
    )

    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=forward.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    assert result["run"]["helius_requests"] == 0


def activation_primary_payload():
    return {
        "campaign_id": PRIMARY_COPY_ID,
        "campaign_role": "PRIMARY_FORWARD",
        "status": "ACTIVE",
        "anchor_at": "2026-08-03T23:04:08.419988+00:00",
        "frozen_wallets": [PRIMARY_A, PRIMARY_B],
        "counts": {"receipt_count": 7, "closed_trade_count": 0},
        "webhook": {
            "status": "ACTIVE",
            "webhook_id": WEBHOOK_ID,
            "url": "https://backend.test/integrity/parser-gen4-copyability/webhook/helius",
        },
    }


def activation_candidate_payload(candidate_id: str):
    return {
        "campaign_id": candidate_id,
        "campaign_role": "QUALIFIED_CANDIDATE",
        "status": "ACTIVE",
        "anchor_at": "2026-08-08T00:00:00+00:00",
        "frozen_wallets": [CANDIDATE],
        "counts": {},
        "webhook": {"status": "ACTIVE", "webhook_id": WEBHOOK_ID},
    }


def test_activation_uses_get_by_id_when_list_view_omits_addresses(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    primary = activation_primary_payload()
    candidate_id = "11111111-2222-3333-4444-555555555555"
    candidate = activation_candidate_payload(candidate_id)
    before = {
        "m61_parallel_candidate_support": True,
        "active_campaign_count": 1,
        "active_campaigns": [primary],
        "safety": {
            "signer_access": False,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "paper_orders_created": 0,
            "live_orders_created": 0,
            "automatic_live_activation": False,
        },
    }
    after = {**before, "active_campaign_count": 2, "active_campaigns": [primary, candidate]}
    status_reads = 0
    backend_calls = []
    helius_calls = []
    by_id_reads = 0

    def fake_backend(_client, method, path, _key, payload=None):
        nonlocal status_reads
        backend_calls.append((method, path, payload))
        if method == "GET" and path == activation.STATUS_PATH:
            status_reads += 1
            return before if status_reads == 1 else after
        if method == "POST" and path == activation.START_PATH:
            return {**candidate, "idempotent_replay": False}
        if method == "POST" and path == activation.CONFIGURE_PATH:
            assert payload["campaign_id"] == candidate_id
            return candidate
        raise AssertionError((method, path, payload))

    def fake_helius(_client, method, url, _key, payload=None):
        nonlocal by_id_reads
        helius_calls.append((method, url, payload))
        if method == "GET" and url == activation.HELIUS_WEBHOOK_API:
            # Provider list view may omit monitored addresses.
            return [{
                "webhookID": WEBHOOK_ID,
                "webhookURL": "https://backend.test" + activation.WEBHOOK_PATH,
                "webhookType": "raw",
                "accountAddresses": [],
                "active": True,
            }]
        if method == "GET" and url.endswith("/" + WEBHOOK_ID):
            by_id_reads += 1
            addresses = (
                [PRIMARY_A, PRIMARY_B]
                if by_id_reads == 1
                else [PRIMARY_A, PRIMARY_B, CANDIDATE]
            )
            return {
                "webhookID": WEBHOOK_ID,
                "webhookURL": "https://backend.test" + activation.WEBHOOK_PATH,
                "webhookType": "raw",
                "transactionTypes": ["ANY"],
                "accountAddresses": addresses,
                "active": True,
            }
        if method == "PUT":
            assert payload["transactionTypes"] == ["ANY"]
            assert set(payload["accountAddresses"]) == {PRIMARY_A, PRIMARY_B, CANDIDATE}
            return {"webhookID": WEBHOOK_ID}
        raise AssertionError((method, url, payload))

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    monkeypatch.setattr(activation, "helius_request", fake_helius)
    state = activation.ActivationState()
    activation.activate(
        object(),
        state=state,
        helius_key="redacted",
        automation_key="redacted",
        webhook_secret="redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    assert state.repaired_empty_webhook is False
    assert set(state.original_addresses or []) == {PRIMARY_A, PRIMARY_B}
    assert set(state.rollback_addresses or []) == {PRIMARY_A, PRIMARY_B}
    assert state.candidate_created_now is True
    assert by_id_reads == 2
    put = next(call for call in helius_calls if call[0] == "PUT")
    assert put[2]["transactionTypes"] == ["ANY"]
    assert set(put[2]["accountAddresses"]) == {PRIMARY_A, PRIMARY_B, CANDIDATE}
    configure_calls = [
        call for call in backend_calls
        if call[0] == "POST" and call[1] == activation.CONFIGURE_PATH
    ]
    assert len(configure_calls) == 1
    assert configure_calls[0][2]["campaign_id"] == candidate_id


def test_activation_rejects_empty_webhook_if_provider_id_does_not_match_primary(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    primary = activation_primary_payload()
    before = {
        "m61_parallel_candidate_support": True,
        "active_campaign_count": 1,
        "active_campaigns": [primary],
        "safety": {},
    }
    backend_calls = []

    def fake_backend(_client, method, path, _key, payload=None):
        backend_calls.append((method, path, payload))
        if method == "GET":
            return before
        raise AssertionError("candidate must not be created before provider validation")

    def fake_helius(_client, method, url, _key, payload=None):
        assert method == "GET" and url == activation.HELIUS_WEBHOOK_API
        return [{
            "webhookID": "different-webhook",
            "webhookURL": "https://backend.test" + activation.WEBHOOK_PATH,
            "webhookType": "raw",
            "accountAddresses": [],
            "active": True,
        }]

    monkeypatch.setattr(activation, "backend_request", fake_backend)
    monkeypatch.setattr(activation, "helius_request", fake_helius)
    with pytest.raises(activation.ActivationError, match="non coincide"):
        activation.activate(
            object(),
            state=activation.ActivationState(),
            helius_key="redacted",
            automation_key="redacted",
            webhook_secret="redacted",
            target_url="https://backend.test" + activation.WEBHOOK_PATH,
        )
    assert [call for call in backend_calls if call[0] == "POST"] == []


def test_httpx_transport_info_logging_is_suppressed():
    source = Path("backend/app/core/logging_config.py").read_text(encoding="utf-8")
    assert '"httpx"' in source
    assert '"httpcore"' in source
    assert source.count('"level": "WARNING"') >= 3


def test_empty_webhook_failsafe_never_restores_broken_empty_address_list(monkeypatch):
    from scripts import activate_gen4_parallel_candidate_m61 as activation

    candidate_id = "11111111-2222-3333-4444-555555555555"
    state = activation.ActivationState(
        candidate_id=candidate_id,
        candidate_created_now=True,
        webhook_id=WEBHOOK_ID,
        primary_webhook_id=WEBHOOK_ID,
        original_addresses=[],
        rollback_addresses=[PRIMARY_A, PRIMARY_B],
        original_transaction_types=["ANY"],
        webhook_updated=True,
        repaired_empty_webhook=True,
    )
    helius_calls = []
    backend_calls = []

    def fake_helius(_client, method, url, _key, payload=None):
        helius_calls.append((method, url, payload))
        return {"webhookID": WEBHOOK_ID}

    def fake_backend(_client, method, path, _key, payload=None):
        backend_calls.append((method, path, payload))
        return {"status": "COMPLETED"}

    monkeypatch.setattr(activation, "helius_request", fake_helius)
    monkeypatch.setattr(activation, "backend_request", fake_backend)
    activation.rollback_activation(
        object(),
        state=state,
        helius_key="redacted",
        automation_key="redacted",
        webhook_secret="redacted",
        target_url="https://backend.test" + activation.WEBHOOK_PATH,
    )

    assert len(helius_calls) == 1
    assert set(helius_calls[0][2]["accountAddresses"]) == {PRIMARY_A, PRIMARY_B}
    assert helius_calls[0][2]["transactionTypes"] == ["ANY"]
    assert helius_calls[0][2]["accountAddresses"] != []
    stop_calls = [
        call for call in backend_calls
        if call[0] == "POST" and call[1] == activation.STOP_PATH
    ]
    assert len(stop_calls) == 1
    assert stop_calls[0][2]["campaign_id"] == candidate_id


def test_m61_raw_webhook_scripts_use_authoritative_detail_and_preserve_transaction_types():
    scripts = {
        "configure": Path("scripts/configure_gen4_copyability_helius_webhook.py").read_text(
            encoding="utf-8"
        ),
        "activate": Path("scripts/activate_gen4_parallel_candidate_m61.py").read_text(
            encoding="utf-8"
        ),
        "rollback": Path("scripts/rollback_gen4_parallel_candidate_m61.py").read_text(
            encoding="utf-8"
        ),
    }

    for name, source in scripts.items():
        assert 'f"{HELIUS_WEBHOOK_API}/{' in source, name
        assert 'transactionTypes' in source, name

    assert '"transactionTypes": ["ANY"]' in scripts["configure"]
    assert 'transaction_types=state.original_transaction_types' in scripts["activate"]
    assert '"transactionTypes": list(transaction_types)' in scripts["rollback"]

    rollback = scripts["rollback"]
    assert "GET /v0/webhooks is a summary view" in rollback
    assert 'if current_addresses != PRIMARY_WALLETS:' in rollback
