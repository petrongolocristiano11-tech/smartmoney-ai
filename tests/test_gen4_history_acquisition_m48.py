from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import gen4_history_acquisition_service as service

NOW = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)
WALLET_A = "A" * 32
WALLET_B = "B" * 32
WALLET_C = "C" * 32
TOKEN = "T" * 32


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _wallet(
    db: Session,
    address: str,
    *,
    quality: str,
    quality_score: float,
    promotion_status: str = "OSSERVAZIONE",
    promotion_eligible: bool = False,
):
    row = DiscoveredWallet(
        wallet_address=address,
        quality_classification=quality,
        quality_score=quality_score,
        quality_eligible=quality in service.AUTO_ALLOWED_QUALITY_CLASSIFICATIONS,
        ranking_score=quality_score - 1,
        smart_score=quality_score - 2,
        promotion_status=promotion_status,
        promotion_eligible=promotion_eligible,
    )
    db.add(row)
    db.flush()
    return row


def _trade(db: Session, wallet: str, at: datetime, index: int):
    db.add(
        Trade(
            signature=f"{wallet}-{index}",
            wallet_address=wallet,
            side="BUY" if index % 2 == 0 else "SELL",
            token_mint=TOKEN,
            token_amount=100.0,
            sol_amount=1.0,
            success=True,
            block_time=at,
        )
    )


def _profitability_report():
    metrics = {
        "closed_trades": 0,
        "total_return_percent": 0.0,
        "profit_factor": None,
        "max_drawdown_percent": 0.0,
    }
    return {
        "verdict": "NOT_EVALUABLE",
        "strict_metrics": dict(metrics),
        "proxy_metrics": dict(metrics),
        "baseline_metrics": dict(metrics),
        "evidence_gaps": ["STRICT_FORWARD_EVIDENCE_REQUIRED"],
    }


def test_preview_is_read_only_and_selects_quality_ranked_wallets(db):
    _wallet(db, WALLET_A, quality="OSSERVAZIONE", quality_score=80)
    _wallet(db, WALLET_B, quality="COPIABILE", quality_score=70)
    _wallet(db, WALLET_C, quality="SOSPETTO", quality_score=99)
    _trade(db, WALLET_A, NOW - timedelta(days=10), 1)
    _trade(db, WALLET_A, NOW, 2)
    db.commit()

    before_wallets = db.query(DiscoveredWallet).count()
    before_trades = db.query(Trade).count()
    plan = service.preview_gen4_history_acquisition(
        db,
        lookback_days=45,
        max_wallets=2,
        max_helius_requests_per_wallet=20,
        evaluated_at=NOW,
    )

    assert plan["selected_wallet_count"] == 2
    assert [row["wallet_address"] for row in plan["selected_wallets"]] == [
        WALLET_B,
        WALLET_A,
    ]
    assert plan["selected_wallets"][1]["history_span_days"] == 10.0
    assert plan["parameters"]["maximum_total_helius_requests"] == 40
    assert plan["safety"]["preview_read_only"] is True
    assert db.query(DiscoveredWallet).count() == before_wallets
    assert db.query(Trade).count() == before_trades


def test_preview_prioritizes_explicit_allowed_wallet_and_rejects_suspicious(db):
    _wallet(db, WALLET_A, quality="OSSERVAZIONE", quality_score=10)
    _wallet(db, WALLET_B, quality="COPIABILE", quality_score=90)
    _wallet(db, WALLET_C, quality="SOSPETTO", quality_score=100)
    db.commit()

    plan = service.preview_gen4_history_acquisition(
        db,
        wallet_addresses=[WALLET_A, WALLET_C],
        max_wallets=2,
    )

    assert plan["selected_wallets"][0]["wallet_address"] == WALLET_A
    assert plan["selected_wallets"][1]["wallet_address"] == WALLET_B
    assert plan["rejected_requested_wallets"] == [
        {
            "wallet_address": WALLET_C,
            "reason": "SUSPICIOUS_WALLET_REJECTED",
        }
    ]



def test_preview_accepts_explicit_non_analyzed_wallet_for_evidence_only(db):
    _wallet(
        db,
        WALLET_A,
        quality="NON_ANALIZZATO",
        quality_score=0,
        promotion_status="OSSERVAZIONE",
    )
    _trade(db, WALLET_A, NOW - timedelta(days=1), 1)
    db.commit()

    plan = service.preview_gen4_history_acquisition(
        db,
        wallet_addresses=[WALLET_A],
        max_wallets=1,
        evaluated_at=NOW,
    )

    assert plan["selected_wallet_count"] == 1
    selected = plan["selected_wallets"][0]
    assert selected["wallet_address"] == WALLET_A
    assert selected["selection_reason"] == "EXPLICIT_RESEARCH_EVIDENCE_ONLY"
    assert selected["evidence_only"] is True
    assert selected["quality_classification"] == "NON_ANALIZZATO"
    assert plan["safety"]["quality_gate_bypassed_for_copying"] is False


def test_preview_auto_research_uses_existing_non_suspicious_evidence(db):
    _wallet(db, WALLET_A, quality="NON_ANALIZZATO", quality_score=0)
    _wallet(db, WALLET_B, quality="NON_COPIABILE", quality_score=20)
    _wallet(db, WALLET_C, quality="SOSPETTO", quality_score=99)
    _trade(db, WALLET_A, NOW - timedelta(days=2), 1)
    _trade(db, WALLET_A, NOW - timedelta(days=1), 2)
    _trade(db, WALLET_B, NOW - timedelta(days=1), 3)
    _trade(db, WALLET_C, NOW - timedelta(days=1), 4)
    db.commit()

    plan = service.preview_gen4_history_acquisition(
        db,
        max_wallets=2,
        evaluated_at=NOW,
    )

    assert [row["wallet_address"] for row in plan["selected_wallets"]] == [
        WALLET_A,
        WALLET_B,
    ]
    assert all(
        row["selection_reason"] == "AUTO_RESEARCH_EXISTING_EVIDENCE"
        for row in plan["selected_wallets"]
    )


def test_budget_hard_limit_is_enforced(db):
    with pytest.raises(
        service.Gen4HistoryAcquisitionError,
        match="limite hard",
    ):
        service.preview_gen4_history_acquisition(
            db,
            max_wallets=3,
            max_helius_requests_per_wallet=20,
        )


def test_execute_requires_exact_confirmation(db):
    _wallet(db, WALLET_A, quality="OSSERVAZIONE", quality_score=80)
    db.commit()

    with pytest.raises(
        service.Gen4HistoryAcquisitionError,
        match="Conferma manuale",
    ):
        service.run_gen4_history_acquisition(
            db,
            confirmation="WRONG",
            max_wallets=1,
        )


def test_execute_uses_no_force_preserves_protected_fields_and_aggregates(
    db,
    monkeypatch,
):
    wallet = _wallet(
        db,
        WALLET_A,
        quality="OSSERVAZIONE",
        quality_score=80,
        promotion_status="BLOCCATO",
        promotion_eligible=False,
    )
    _trade(db, WALLET_A, NOW - timedelta(days=1), 1)
    db.commit()
    calls = []

    def fake_run(session, **kwargs):
        calls.append(kwargs)
        _trade(session, WALLET_A, NOW - timedelta(days=30), 2)
        session.commit()
        return SimpleNamespace(
            run_id="run-1",
            status="COMPLETED",
            stop_reason="LOOKBACK_REACHED",
            error_code=None,
            error_message=None,
            helius_requests=4,
            trades_imported=1,
            trades_updated=0,
            parse_failures=0,
        )

    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        fake_run,
    )
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: _profitability_report(),
    )

    report = service.run_gen4_history_acquisition(
        db,
        confirmation=service.GEN4_HISTORY_ACQUISITION_CONFIRMATION,
        wallet_addresses=[WALLET_A],
        max_wallets=1,
        evaluated_at=NOW,
    )

    assert calls[0]["force"] is False
    assert calls[0]["evidence_only"] is True
    assert calls[0]["lookback_days"] == 45
    assert report["summary"]["helius_requests"] == 4
    assert report["summary"]["trades_imported"] == 1
    assert report["wallet_results"][0]["after"]["history_span_days"] == 29.0
    db.refresh(wallet)
    assert wallet.quality_classification == "OSSERVAZIONE"
    assert wallet.promotion_status == "BLOCCATO"
    assert wallet.promotion_eligible is False
    assert report["safety"]["transactions_sent"] == 0


def test_execute_restores_protected_fields_if_dependency_changes_them(
    db,
    monkeypatch,
):
    wallet = _wallet(
        db,
        WALLET_A,
        quality="OSSERVAZIONE",
        quality_score=80,
        promotion_status="OSSERVAZIONE",
        promotion_eligible=False,
    )
    db.commit()

    def fake_run(session, **_kwargs):
        row = session.query(DiscoveredWallet).filter_by(
            wallet_address=WALLET_A
        ).one()
        row.promotion_status = "PROMOSSO"
        row.promotion_eligible = True
        session.commit()
        return SimpleNamespace(
            run_id="run-2",
            status="COMPLETED",
            stop_reason="LAST_PAGE",
            error_code=None,
            error_message=None,
            helius_requests=1,
            trades_imported=0,
            trades_updated=0,
            parse_failures=0,
        )

    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        fake_run,
    )

    with pytest.raises(
        service.Gen4HistoryAcquisitionError,
        match="valori originari sono stati ripristinati",
    ):
        service.run_gen4_history_acquisition(
            db,
            confirmation=service.GEN4_HISTORY_ACQUISITION_CONFIRMATION,
            wallet_addresses=[WALLET_A],
            max_wallets=1,
            evaluated_at=NOW,
        )

    db.refresh(wallet)
    assert wallet.promotion_status == "OSSERVAZIONE"
    assert wallet.promotion_eligible is False


def test_completed_backfill_is_reported_without_external_requests(db, monkeypatch):
    _wallet(db, WALLET_A, quality="COPIABILE", quality_score=80)
    db.commit()

    def fake_run(*_args, **_kwargs):
        raise ValueError(
            "Lo storico richiesto è già stato completato. Aumenta il lookback."
        )

    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        fake_run,
    )
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: _profitability_report(),
    )

    report = service.run_gen4_history_acquisition(
        db,
        confirmation=service.GEN4_HISTORY_ACQUISITION_CONFIRMATION,
        max_wallets=1,
        evaluated_at=NOW,
    )

    result = report["wallet_results"][0]
    assert result["status"] == "SKIPPED_ALREADY_COMPLETE"
    assert result["helius_requests"] == 0
    assert report["summary"]["helius_requests"] == 0


def test_no_eligible_wallets_is_rejected(db):
    _wallet(db, WALLET_C, quality="SOSPETTO", quality_score=100)
    db.commit()

    with pytest.raises(
        service.Gen4HistoryAcquisitionError,
        match="Nessun wallet",
    ):
        service.run_gen4_history_acquisition(
            db,
            confirmation=service.GEN4_HISTORY_ACQUISITION_CONFIRMATION,
            max_wallets=1,
            evaluated_at=NOW,
        )


def test_preview_accepts_explicit_external_wallet_without_creating_record(db):
    external_wallet = "D" * 32
    before_wallet_count = db.query(DiscoveredWallet).count()

    plan = service.preview_gen4_history_acquisition(
        db,
        wallet_addresses=[external_wallet],
        max_wallets=1,
        evaluated_at=NOW,
    )

    assert plan["selected_wallet_count"] == 1
    selected = plan["selected_wallets"][0]
    assert selected["wallet_address"] == external_wallet
    assert selected["selection_reason"] == "EXPLICIT_EXTERNAL_EVIDENCE_ONLY"
    assert selected["wallet_record_present"] is False
    assert selected["quality_classification"] == "NOT_REGISTERED"
    assert selected["promotion_status"] == "NOT_REGISTERED"
    assert plan["rejected_requested_wallets"] == []
    assert db.query(DiscoveredWallet).count() == before_wallet_count


def test_execute_external_wallet_imports_evidence_without_discovery_record(
    db,
    monkeypatch,
):
    external_wallet = "D" * 32
    calls = []

    def fake_run(session, **kwargs):
        calls.append(kwargs)
        _trade(session, external_wallet, NOW - timedelta(days=30), 99)
        session.commit()
        return SimpleNamespace(
            run_id="external-run",
            status="COMPLETED",
            stop_reason="LOOKBACK_REACHED",
            error_code=None,
            error_message=None,
            helius_requests=2,
            trades_imported=1,
            trades_updated=0,
            parse_failures=0,
        )

    monkeypatch.setattr(
        service.candidate_history_service,
        "run_extended_candidate_history",
        fake_run,
    )
    monkeypatch.setattr(
        service,
        "preview_gen4_profitability",
        lambda *_args, **_kwargs: _profitability_report(),
    )

    report = service.run_gen4_history_acquisition(
        db,
        confirmation=service.GEN4_HISTORY_ACQUISITION_CONFIRMATION,
        wallet_addresses=[external_wallet],
        max_wallets=1,
        evaluated_at=NOW,
    )

    assert calls[0]["evidence_only"] is True
    assert calls[0]["force"] is False
    assert report["summary"]["helius_requests"] == 2
    result = report["wallet_results"][0]
    assert result["wallet_record_present_before"] is False
    assert result["wallet_record_present_after"] is False
    assert result["discovered_wallet_record_created"] is False
    assert (
        db.query(DiscoveredWallet)
        .filter_by(wallet_address=external_wallet)
        .first()
        is None
    )
    assert report["safety"]["external_discovered_wallet_records_created"] == 0
