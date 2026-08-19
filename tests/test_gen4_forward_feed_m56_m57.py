from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.gen4_forward_feed import (
    CanonicalParserGen4ForwardFeedRun,
    CanonicalParserGen4ForwardFeedState,
)
from backend.app.models.gen4_forward_shadow import CanonicalParserGen4ForwardCampaign
from backend.app.services import blockchain_parser_gen4_forward_feed_service as feed_service
from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
    GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION,
    GEN4_FORWARD_FEED_POLL_CONFIRMATION,
    CanonicalParserGen4ForwardFeedError,
    configure_gen4_forward_feed,
    get_gen4_forward_feed_status,
    run_gen4_forward_feed_poll,
)

NOW = datetime(2026, 8, 2, 18, 30, tzinfo=timezone.utc)
WALLET_A = "FeedWalletA111111111111111111111111111111111111"
WALLET_B = "FeedWalletB111111111111111111111111111111111111"
TOKEN = "FeedToken11111111111111111111111111111111111111"


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


def _campaign(db: Session) -> CanonicalParserGen4ForwardCampaign:
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
        frozen_wallets=[WALLET_A, WALLET_B],
        frozen_wallet_metrics={},
        frozen_wallet_count=2,
        anchor_at=NOW - timedelta(minutes=2),
        minimum_complete_at=NOW + timedelta(days=21),
        latest_observed_at=NOW - timedelta(seconds=30),
        started_at=NOW - timedelta(minutes=2),
        completed_at=None,
        minimum_observation_days=21,
        minimum_closed_trades=30,
        proof_closed_trades=100,
        cycle_count=1,
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
    db.commit()
    return row


def _tx(seconds_before: int, signature: str) -> dict:
    return {
        "type": "SWAP",
        "signature": signature,
        "timestamp": int((NOW - timedelta(seconds=seconds_before)).timestamp()),
    }


def test_models_and_migration_extend_single_head():
    assert "canonical_parser_gen4_forward_feed_states" in Base.metadata.tables
    assert "canonical_parser_gen4_forward_feed_runs" in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("a5e7c1d4b926").down_revision == "f4d6a9c2b813"
    assert scripts.get_heads() == ["d9b2e4f7a153"]


def test_status_creates_persistent_state_for_active_campaign(db):
    campaign = _campaign(db)
    result = get_gen4_forward_feed_status(db)
    db.commit()
    assert result["campaign_id"] == campaign.campaign_id
    assert result["state"]["enabled"] is True
    assert result["state"]["interval_seconds"] == 120
    assert db.query(CanonicalParserGen4ForwardFeedState).count() == 1


def test_configure_requires_confirmation_and_updates_limits(db):
    campaign = _campaign(db)
    with pytest.raises(CanonicalParserGen4ForwardFeedError) as error:
        configure_gen4_forward_feed(
            db,
            campaign_id=campaign.campaign_id,
            confirmation="WRONG",
            enabled=True,
        )
    assert error.value.code == "GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION_REQUIRED"
    result = configure_gen4_forward_feed(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION,
        enabled=True,
        interval_seconds=60,
        max_requests_per_run=6,
    )
    db.commit()
    assert result["state"]["interval_seconds"] == 60
    assert result["state"]["max_requests_per_run"] == 6


def test_poll_filters_stale_transactions_imports_recent_and_runs_cycle(db, monkeypatch):
    campaign = _campaign(db)
    status = get_gen4_forward_feed_status(db)
    state = db.query(CanonicalParserGen4ForwardFeedState).one()
    state.feed_started_at = NOW - timedelta(minutes=10)
    db.commit()

    calls: list[dict] = []
    saved: list[dict] = []

    def fake_history(address, **kwargs):
        calls.append({"address": address, **kwargs})
        return [
            _tx(30, f"{address}-recent"),
            _tx(600, f"{address}-stale"),
        ]

    def fake_save(db, *, wallet_address, transactions):
        saved.extend(transactions)
        return {
            "transactions_found": len(transactions),
            "swaps_found": len(transactions),
            "trades_imported": len(transactions),
            "trades_updated": 0,
            "parse_failures": 0,
        }

    def fake_cycle(db, *, campaign_id, confirmation, observed_at):
        assert campaign_id == campaign.campaign_id
        return {
            "cycle": {
                "cycle_id": str(uuid4()),
                "sequence": 2,
                "status": "COMPLETED",
                "new_decision_count": 1,
                "updated_decision_count": 0,
            },
            "campaign": {},
        }

    monkeypatch.setattr(feed_service, "get_wallet_history", fake_history)
    monkeypatch.setattr(feed_service, "save_wallet_history_transactions", fake_save)
    monkeypatch.setattr(feed_service, "run_gen4_forward_cycle", fake_cycle)

    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    db.commit()
    assert len(calls) == 2
    assert len(saved) == 2
    assert result["run"]["trades_imported"] == 2
    assert result["run"]["stale_transactions_filtered"] == 2
    assert result["run"]["new_decisions"] == 1
    assert result["run"]["safety"]["paper_orders_created"] == 0
    assert db.query(CanonicalParserGen4ForwardFeedRun).count() == 1


def test_poll_skips_when_lease_is_active(db):
    campaign = _campaign(db)
    get_gen4_forward_feed_status(db)
    state = db.query(CanonicalParserGen4ForwardFeedState).one()
    state.lease_owner = "other-worker"
    state.lease_expires_at = NOW + timedelta(minutes=2)
    db.commit()
    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    assert result["run"]["status"] == "SKIPPED_LOCKED"
    assert result["run"]["helius_requests"] == 0


def test_poll_enforces_daily_request_cap(db, monkeypatch):
    campaign = _campaign(db)
    get_gen4_forward_feed_status(db)
    state = db.query(CanonicalParserGen4ForwardFeedState).one()
    monkeypatch.setattr(feed_service.settings, "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP", 1)
    prior = CanonicalParserGen4ForwardFeedRun(
        run_id=str(uuid4()),
        state_db_id=state.id,
        campaign_db_id=campaign.id,
        trigger="MANUAL",
        status="NOOP",
        owner_id="prior",
        observed_from_at=NOW - timedelta(minutes=2),
        observed_to_at=NOW - timedelta(minutes=1),
        wallet_count=2,
        request_budget=1,
        helius_requests=1,
        transactions_found=0,
        swaps_found=0,
        trades_imported=0,
        trades_updated=0,
        parse_failures=0,
        stale_transactions_filtered=0,
        new_decisions=0,
        updated_decisions=0,
        details={},
        safety={},
        started_at=NOW - timedelta(minutes=2),
        completed_at=NOW - timedelta(minutes=1),
    )
    db.add(prior)
    db.commit()
    result = run_gen4_forward_feed_poll(
        db,
        campaign_id=campaign.campaign_id,
        confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
        observed_at=NOW,
    )
    assert result["run"]["status"] == "SKIPPED_BUDGET"
    assert result["run"]["error_code"] == "GEN4_FORWARD_FEED_DAILY_REQUEST_CAP_REACHED"
