from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_token_compatibility import CandidateTokenCompatibility
from backend.app.services.candidate_jupiter_compatibility_service import (
    check_candidate_jupiter_compatibility,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
TOKEN = "C" * 32


class FakeJupiter:
    def __init__(self):
        self.calls = []

    def get_order(self, *, input_mint, output_mint, amount_raw, taker, slippage_bps):
        self.calls.append((input_mint, output_mint, amount_raw, slippage_bps))
        return SimpleNamespace(out_amount=max(1, amount_raw * 2))


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)()


def test_compatibility_is_cached_by_token_size_and_slippage():
    engine, db = make_db()
    try:
        first_client = FakeJupiter()
        first = check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=first_client,
            now=NOW,
        )
        db.commit()

        second_client = FakeJupiter()
        second = check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=second_client,
            now=NOW + timedelta(hours=1),
        )

        assert first["requests"] == 2
        assert first["live_checks"] == 1
        assert first["cache_hits"] == 0
        assert len(first_client.calls) == 2
        assert second["requests"] == 0
        assert second["live_checks"] == 0
        assert second["cache_hits"] == 1
        assert second["status"] == "PASSED"
        assert second["results"][0]["source"] == "CACHE"
        assert second_client.calls == []
        assert db.query(CandidateTokenCompatibility).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_force_refresh_bypasses_valid_cache():
    engine, db = make_db()
    try:
        check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=FakeJupiter(),
            now=NOW,
        )
        db.commit()

        client = FakeJupiter()
        result = check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=client,
            force_refresh=True,
            now=NOW + timedelta(hours=1),
        )

        assert result["requests"] == 2
        assert result["cache_hits"] == 0
        assert result["live_checks"] == 1
        assert len(client.calls) == 2
        assert db.query(CandidateTokenCompatibility).count() == 1
    finally:
        db.close()
        engine.dispose()


def test_expired_cache_is_refreshed():
    engine, db = make_db()
    try:
        check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=FakeJupiter(),
            cache_ttl_hours=1,
            now=NOW,
        )
        db.commit()

        client = FakeJupiter()
        result = check_candidate_jupiter_compatibility(
            db,
            [TOKEN],
            fixed_buy_size_sol=0.05,
            slippage_bps=100,
            token_limit=10,
            client=client,
            cache_ttl_hours=1,
            now=NOW + timedelta(hours=2),
        )

        assert result["requests"] == 2
        assert result["cache_hits"] == 0
        assert result["live_checks"] == 1
        assert len(client.calls) == 2
    finally:
        db.close()
        engine.dispose()
