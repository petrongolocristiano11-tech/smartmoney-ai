from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from pathlib import Path
import os
import subprocess
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-helius-key-1234567890")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import gen4_evidence_sprint_service as service

NOW = datetime(2026, 8, 2, 14, 0, tzinfo=timezone.utc)
SEED = "7" * 44
CANDIDATE = "8" * 44
SUSPICIOUS = "9" * 44
TOKEN = "A" * 44
TOKEN_2 = "B" * 44


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Trade.__table__.create(engine)
    DiscoveredWallet.__table__.create(engine)
    with Session(engine) as session:
        yield session


def add_trade(db: Session, *, wallet: str, token: str, side: str, at: datetime, seq: int):
    db.add(
        Trade(
            signature=f"sig-{wallet[:4]}-{token[:4]}-{seq}-{int(at.timestamp())}",
            wallet_address=wallet,
            side=side,
            token_mint=token,
            token_amount=100.0,
            sol_amount=1.0,
            success=True,
            block_time=at,
        )
    )
    db.commit()


def seed_history(db: Session):
    add_trade(db, wallet=SEED, token=TOKEN, side="BUY", at=NOW - timedelta(days=44), seq=1)
    add_trade(db, wallet=SEED, token=TOKEN, side="SELL", at=NOW - timedelta(days=30), seq=2)
    add_trade(db, wallet=SEED, token=TOKEN_2, side="BUY", at=NOW - timedelta(days=20), seq=3)
    add_trade(db, wallet=SEED, token=TOKEN_2, side="SELL", at=NOW - timedelta(days=1), seq=4)


def profitability_report(*, proxy_closed: int = 0, qualified: int = 0, signals: int = 0):
    return {
        "verdict": "NOT_EVALUABLE",
        "strict_evidence_status": "INSUFFICIENT",
        "policy_snapshot": {"minimum_evaluable_closed_trades": 30},
        "strict_metrics": {
            "closed_trades": 0,
            "total_return_percent": 0.0,
            "profit_factor": None,
            "max_drawdown_percent": 0.0,
        },
        "proxy_metrics": {
            "closed_trades": proxy_closed,
            "total_return_percent": 2.5 if proxy_closed else 0.0,
            "profit_factor": 1.4 if proxy_closed else None,
            "max_drawdown_percent": 3.0 if proxy_closed else 0.0,
        },
        "baseline_metrics": {
            "closed_trades": 2 if proxy_closed else 0,
            "total_return_percent": 1.0 if proxy_closed else 0.0,
            "profit_factor": 1.1 if proxy_closed else None,
            "max_drawdown_percent": 2.0 if proxy_closed else 0.0,
        },
        "windows": [
            {
                "sequence": 1,
                "train_start_at": NOW - timedelta(days=21),
                "train_end_at": NOW - timedelta(days=7),
                "test_start_at": NOW - timedelta(days=7),
                "test_end_at": NOW,
                "proxy_qualified_wallet_count": qualified,
                "proxy_signal_count": signals,
                "baseline_signal_count": signals,
                "evidence": {
                    "proxy_training_wallet_metrics": {
                        SEED: {
                            "qualified": qualified > 0,
                            "reason_codes": [] if qualified > 0 else ["TRAINING_OPEN_POSITIONS_ABOVE_MAXIMUM"],
                        }
                    },
                    "proxy_signal_audit": {"skipped_reason_counts": {}},
                },
            }
        ],
        "evidence_gaps": ["POINT_IN_TIME_WALLET_BACKTEST_COVERAGE_INCOMPLETE"],
    }


def transaction(wallet: str, at: datetime):
    return {
        "type": "SWAP",
        "feePayer": wallet,
        "timestamp": int(at.timestamp()),
        "signature": f"tx-{wallet[:4]}-{int(at.timestamp())}",
    }


def test_preview_is_read_only_and_ranks_round_trip_tokens(db):
    seed_history(db)
    report = service.preview_gen4_evidence_sprint(
        db,
        priority_wallet=SEED,
        max_token_discovery_requests=2,
        evaluated_at=NOW,
    )
    assert report["priority_wallet_stats"]["history_span_days"] == 43.0
    assert report["seed_tokens"][0]["token_mint"] in {TOKEN, TOKEN_2}
    assert report["parameters"]["maximum_total_helius_requests"] == 25
    assert report["safety"]["preview_read_only"] is True


def test_invalid_total_budget_is_rejected(db):
    seed_history(db)
    with pytest.raises(service.Gen4EvidenceSprintError) as exc:
        service.preview_gen4_evidence_sprint(
            db,
            priority_wallet=SEED,
            max_token_discovery_requests=8,
            max_candidate_probes=12,
            max_companions=2,
            max_backfill_requests_per_wallet=20,
            evaluated_at=NOW,
        )
    assert exc.value.code == "TOTAL_REQUEST_BUDGET_EXCEEDED"


def test_extract_fee_payers_filters_seed_and_non_swaps():
    rows = [
        transaction(SEED, NOW),
        transaction(CANDIDATE, NOW),
        {"type": "TRANSFER", "feePayer": "C" * 44},
        {"type": "SWAP", "feePayer": "short"},
    ]
    assert service._extract_fee_payers(rows, excluded_wallets={SEED}) == {CANDIDATE}


def test_probe_metrics_and_candidate_score_prefer_manageable_activity():
    slow = service._probe_metrics(
        [transaction(CANDIDATE, NOW), transaction(CANDIDATE, NOW - timedelta(days=5))]
    )
    fast = service._probe_metrics(
        [transaction(CANDIDATE, NOW), transaction(CANDIDATE, NOW - timedelta(hours=2))]
    )
    common = {
        "shared_tokens": [TOKEN],
        "local_stats": {"history_span_days": 0.0},
    }
    assert service._candidate_score({**common, "probe": slow}) > service._candidate_score(
        {**common, "probe": fast}
    )


def test_run_scouts_backfills_and_returns_visible_proxy(monkeypatch, db):
    seed_history(db)
    calls = []

    def fake_history(address, **kwargs):
        calls.append(address)
        if address in {TOKEN, TOKEN_2}:
            return [transaction(CANDIDATE, NOW - timedelta(days=1))]
        if address == CANDIDATE:
            return [
                transaction(CANDIDATE, NOW),
                transaction(CANDIDATE, NOW - timedelta(days=6)),
            ]
        raise AssertionError(address)

    def fake_backfill(session, **kwargs):
        assert kwargs["evidence_only"] is True
        assert kwargs["force"] is False
        add_trade(session, wallet=CANDIDATE, token=TOKEN, side="BUY", at=NOW - timedelta(days=35), seq=10)
        add_trade(session, wallet=CANDIDATE, token=TOKEN, side="SELL", at=NOW - timedelta(days=1), seq=11)
        return SimpleNamespace(
            status="COMPLETED",
            stop_reason="LOOKBACK_REACHED",
            run_id="run-1",
            helius_requests=3,
            trades_imported=2,
            trades_updated=0,
            error_code=None,
            error_message=None,
        )

    monkeypatch.setattr(service, "get_wallet_history", fake_history)
    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        fake_backfill,
    )
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: profitability_report(
            proxy_closed=4, qualified=2, signals=3
        ),
    )

    before_wallet_count = db.query(DiscoveredWallet).count()
    report = service.run_gen4_evidence_sprint(
        db,
        confirmation=service.GEN4_EVIDENCE_SPRINT_CONFIRMATION,
        priority_wallet=SEED,
        max_token_discovery_requests=2,
        max_candidate_probes=2,
        max_companions=1,
        max_backfill_requests_per_wallet=10,
        evaluated_at=NOW,
    )
    assert report["summary"]["helius_requests"] == 6
    assert report["summary"]["companions_with_21_days"] == 1
    assert report["summary"]["economic_result_status"] == "PROXY_SAMPLE_VISIBLE"
    assert report["summary"]["proxy_closed_trades"] == 4
    assert report["safety"]["strict_gen4_reconstructed_retroactively"] is False
    assert db.query(DiscoveredWallet).count() == before_wallet_count
    assert CANDIDATE in calls


def test_suspicious_candidate_is_never_probed(monkeypatch, db):
    seed_history(db)
    db.add(
        DiscoveredWallet(
            wallet_address=SUSPICIOUS,
            quality_classification="SOSPETTO",
        )
    )
    db.commit()
    calls = []

    def fake_history(address, **kwargs):
        calls.append(address)
        if address in {TOKEN, TOKEN_2}:
            return [transaction(SUSPICIOUS, NOW)]
        raise AssertionError("Il wallet sospetto non deve essere sondato")

    monkeypatch.setattr(service, "get_wallet_history", fake_history)
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: profitability_report(),
    )
    report = service.run_gen4_evidence_sprint(
        db,
        confirmation=service.GEN4_EVIDENCE_SPRINT_CONFIRMATION,
        priority_wallet=SEED,
        max_token_discovery_requests=2,
        max_candidate_probes=2,
        max_companions=1,
        max_backfill_requests_per_wallet=10,
        evaluated_at=NOW,
    )
    assert report["selected_companions"] == []
    assert calls == [TOKEN, TOKEN_2] or calls == [TOKEN_2, TOKEN]


@pytest.mark.parametrize(
    ("closed", "qualified", "signals", "expected"),
    [
        (30, 2, 3, "PROXY_EVALUABLE_NOT_PROOF"),
        (1, 2, 1, "PROXY_SAMPLE_VISIBLE"),
        (0, 2, 0, "QUALIFIED_WALLETS_BUT_NO_CONSENSUS_SIGNALS"),
        (0, 1, 0, "WALLET_TRAINING_GATES_NOT_MET"),
    ],
)
def test_economic_status(closed, qualified, signals, expected):
    assert service._economic_status(
        profitability_report(proxy_closed=closed, qualified=qualified, signals=signals)
    ) == expected


def test_local_history_skips_backfill(monkeypatch, db):
    seed_history(db)
    add_trade(db, wallet=CANDIDATE, token=TOKEN, side="BUY", at=NOW - timedelta(days=30), seq=20)
    add_trade(db, wallet=CANDIDATE, token=TOKEN, side="SELL", at=NOW - timedelta(days=1), seq=21)

    def fake_history(address, **kwargs):
        if address in {TOKEN, TOKEN_2}:
            return [transaction(CANDIDATE, NOW)]
        if address == CANDIDATE:
            return [transaction(CANDIDATE, NOW), transaction(CANDIDATE, NOW - timedelta(days=3))]
        raise AssertionError(address)

    monkeypatch.setattr(service, "get_wallet_history", fake_history)
    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("backfill non atteso")),
    )
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: profitability_report(),
    )
    report = service.run_gen4_evidence_sprint(
        db,
        confirmation=service.GEN4_EVIDENCE_SPRINT_CONFIRMATION,
        priority_wallet=SEED,
        max_token_discovery_requests=2,
        max_candidate_probes=2,
        max_companions=1,
        max_backfill_requests_per_wallet=10,
        evaluated_at=NOW,
    )
    assert report["backfill_results"][0]["status"] == "SKIPPED_LOCAL_HISTORY_SUFFICIENT"
    assert report["summary"]["companions_with_21_days"] == 1

def test_cli_bootstraps_project_root_from_external_working_directory(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / "scripts" / "run_gen4_evidence_sprint.py"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--priority-wallet" in completed.stdout
