from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models  # noqa: F401
from backend.app.core.config import Settings
from backend.app.database.base import Base
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLivePosition,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserLiveOnchainSettlementEvent,
)
from backend.app.services.solana_rpc import SolanaRpcClient
import backend.app.services.blockchain_parser_live_onchain_settlement_service as service
from tests.test_parser_controlled_live_submission_m38 import submit_ready
from tests.test_parser_live_transaction_dry_run_m36 import NOW, TOKEN, WALLET


def settings_for_m39(**overrides):
    values = {
        "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_ENABLED": True,
        "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_RPC_ENABLED": True,
        "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_REQUIRE_FINALIZED": True,
        "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_TRANSACTION_AGE_SECONDS": 900,
        "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_BUY_INPUT_DEVIATION_BPS": 3000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TxRpc:
    def __init__(self, transaction):
        self.transaction = transaction
        self.calls = 0

    def get_transaction_details(self, signature):
        self.calls += 1
        return self.transaction


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def buy_transaction(*, failed=False, token_delta=1_000_000):
    return {
        "slot": 123456,
        "blockTime": int((NOW + timedelta(seconds=3)).timestamp()),
        "transaction": {
            "signatures": ["5" * 88],
            "message": {"accountKeys": [WALLET, "token-account"]},
        },
        "meta": {
            "err": {"InstructionError": [1, "Custom"]} if failed else None,
            "fee": 5000,
            "preBalances": [1_000_000_000, 2_039_280],
            "postBalances": [989_995_000, 2_039_280],
            "preTokenBalances": [
                {"accountIndex": 1, "mint": TOKEN, "owner": WALLET, "uiTokenAmount": {"amount": "0"}}
            ],
            "postTokenBalances": [
                {"accountIndex": 1, "mint": TOKEN, "owner": WALLET, "uiTokenAmount": {"amount": str(token_delta)}}
            ],
        },
    }


def finalized_submission(db, monkeypatch):
    _, _, result, _ = submit_ready(db, monkeypatch, submission_token="m39-submit-001")
    row = db.scalar(select(CanonicalParserControlledLiveSubmission).where(CanonicalParserControlledLiveSubmission.submission_id == result["submission_id"]))
    row.status = "FINALIZED"
    row.confirmation_status = "finalized"
    row.finalized_at = NOW + timedelta(seconds=3)
    db.commit()
    return row


def settle_buy(db, monkeypatch):
    submission = finalized_submission(db, monkeypatch)
    rpc = TxRpc(buy_transaction())
    preview = service.preview_live_onchain_settlement(
        db, submission_id=submission.submission_id, settings_object=settings_for_m39(),
        evaluated_at=NOW + timedelta(seconds=4), rpc_client=rpc,
    )
    result = service.settle_live_onchain_submission(
        db, submission_id=submission.submission_id, confirmation=preview["confirmation"],
        settings_object=settings_for_m39(), settled_at=NOW + timedelta(seconds=4), rpc_client=rpc,
    )
    return submission, result, rpc


def test_m39_flags_false_by_default():
    configured = Settings(_env_file=None, DATABASE_URL="sqlite+pysqlite:///:memory:", SOLANA_RPC_URL="https://api.mainnet-beta.solana.com", HELIUS_API_KEY="test")
    assert configured.CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_RPC_ENABLED is False
    assert configured.CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_REQUIRE_FINALIZED is True


def test_m39_models_registered():
    for table in (
        "canonical_parser_live_onchain_settlements",
        "canonical_parser_live_onchain_settlement_events",
        "canonical_parser_governed_live_positions",
    ):
        assert table in Base.metadata.tables


def test_m39_migration_is_consecutive():
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision("b4e6f9a2c308").down_revision == "a3d5e8f1b297"


def test_rpc_get_transaction_is_read_only_and_finalized():
    captured = {}
    def handler(request: httpx.Request):
        import json; captured.update(json.loads(request.content))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": buy_transaction()})
    client = SolanaRpcClient(rpc_url="https://rpc.test", transport=httpx.MockTransport(handler))
    assert client.get_transaction_details("sig")["slot"] == 123456
    assert captured["method"] == "getTransaction"
    assert captured["params"][1]["commitment"] == "finalized"
    assert captured["params"][1]["encoding"] == "json"
    assert captured["params"][1]["maxSupportedTransactionVersion"] == 1


def test_preview_requires_finalized_submission(db, monkeypatch):
    _, _, result, _ = submit_ready(db, monkeypatch, submission_token="m39-not-final-001")
    preview = service.preview_live_onchain_settlement(
        db, submission_id=result["submission_id"], settings_object=settings_for_m39(),
        evaluated_at=NOW + timedelta(seconds=4), rpc_client=TxRpc(buy_transaction()),
    )
    assert preview["status"] == "INSUFFICIENT_DATA"
    assert "SUBMISSION_NOT_FINALIZED" in preview["reason_codes"]


def test_buy_settlement_opens_governed_position(db, monkeypatch):
    _, result, rpc = settle_buy(db, monkeypatch)
    assert result["status"] == "SETTLED"
    assert result["actual_input_sol"] == "0.010000000"
    assert result["token_delta_raw"] == "1000000"
    assert result["position"]["status"] == "OPEN"
    assert result["position"]["quantity_raw"] == "1000000"
    assert result["position"]["cost_basis_sol"] == "0.010005000"
    assert rpc.calls == 2
    assert db.query(CanonicalParserLiveOnchainSettlement).count() == 1
    assert db.query(CanonicalParserGovernedLivePosition).count() == 1
    assert db.query(CanonicalParserLiveOnchainSettlementEvent).count() == 2


def test_settlement_is_idempotent_by_submission(db, monkeypatch):
    submission, result, _ = settle_buy(db, monkeypatch)
    second = service.settle_live_onchain_submission(
        db, submission_id=submission.submission_id, confirmation="ignored",
        settings_object=settings_for_m39(), settled_at=NOW + timedelta(seconds=5), rpc_client=TxRpc(buy_transaction()),
    )
    assert second["settlement_id"] == result["settlement_id"]
    assert db.query(CanonicalParserLiveOnchainSettlement).count() == 1


def test_failed_chain_transaction_is_blocked(db, monkeypatch):
    submission = finalized_submission(db, monkeypatch)
    preview = service.preview_live_onchain_settlement(
        db, submission_id=submission.submission_id, settings_object=settings_for_m39(),
        evaluated_at=NOW + timedelta(seconds=4), rpc_client=TxRpc(buy_transaction(failed=True)),
    )
    assert preview["status"] == "BLOCKED"
    assert "CHAIN_TRANSACTION_FAILED" in preview["reason_codes"]


def test_raw_transaction_is_never_persisted(db, monkeypatch):
    _, result, _ = settle_buy(db, monkeypatch)
    row = db.scalar(select(CanonicalParserLiveOnchainSettlement))
    assert row.transaction_snapshot["raw_transaction_persisted"] is False
    assert "preBalances" not in str(row.transaction_snapshot)
    assert result["transaction_snapshot"]["raw_transaction_persisted"] is False


def test_service_has_no_legacy_position_or_trade_writes():
    tree = ast.parse(Path(service.__file__).read_text())
    names = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "send_signed_transaction_base64" not in names
    source = Path(service.__file__).read_text()
    assert "backend.app.models.live_position" not in source
    assert "backend.app.models.trade" not in source
