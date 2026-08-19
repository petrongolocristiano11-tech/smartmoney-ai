from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

import pytest

from backend.app.core.constants import SOL_MINT, USDC_MINT
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)
from backend.app.services.helius import helius_rpc_credit_cost
from backend.app.services.gen4_m82_paid_rpc_sprint_service import (
    M82_GTFA_CREDITS_PER_REQUEST,
    M82_MAX_RPC_CREDITS,
    M82_PASS1_TRANSACTIONS,
    M82_PASS2_TRANSACTIONS,
    M82_PASS3_TRANSACTIONS,
    build_model_policy,
    discover_candidates,
    select_discovery_tokens,
)

WALLET = "G4gEznDioDKdK52o66Lhye4h27j43s3JynH2pgnoo2vn"
TOKEN = "BdmmbhuqmMcswTCpP5Dy9H6E87ZqDMULVAWdzu4ZhqTS"


def _payload(
    *,
    signature: str = "regression-signature",
    native_delta: int = -10_100_000,
    fee: int = 100_000,
    token_pre: int = 0,
    token_post: int = 1_000_000,
    extra_pre: list[dict] | None = None,
    extra_post: list[dict] | None = None,
):
    native_pre = 1_000_000_000
    return {
        "signature": signature,
        "slot": 123,
        "blockTime": 1_786_000_000,
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": [native_pre],
            "postBalances": [native_pre + native_delta],
            "preTokenBalances": [
                {
                    "owner": WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {"amount": str(token_pre), "decimals": 6},
                },
                *(extra_pre or []),
            ],
            "postTokenBalances": [
                {
                    "owner": WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {"amount": str(token_post), "decimals": 6},
                },
                *(extra_post or []),
            ],
        },
        "transaction": {
            "signatures": [signature],
            "message": {
                "accountKeys": [
                    {
                        "pubkey": WALLET,
                        "signer": True,
                        "writable": True,
                        "source": "transaction",
                    }
                ]
            },
        },
    }


def _balance(owner: str, mint: str, amount: int, decimals: int) -> dict:
    return {
        "owner": owner,
        "mint": mint,
        "uiTokenAmount": {"amount": str(amount), "decimals": decimals},
    }


def test_m82_parser_version_is_bumped():
    assert GEN4_COPYABILITY_RAW_PARSER_VERSION == "canonical-parser-gen4-raw-balance-delta/4"


def test_m82_rejects_real_regression_shape_usdc_routed_buy():
    payload = _payload(
        signature="3wJaTL9PrMtnxN5BomV1HFmf8BCypmP2Vm6u8SzNyaFGBUeECGugUWLH51AzjHF8sCF1LpNg4TheiRUnGY7TZ6Mn",
        native_delta=-95_978,
        fee=68_685,
        token_pre=0,
        token_post=7_290_049_656_912,
        extra_pre=[_balance(WALLET, USDC_MINT, 150_288_129, 6)],
        extra_post=[_balance(WALLET, USDC_MINT, 75_144_065, 6)],
    )
    with pytest.raises(CanonicalParserGen4CopyabilityError) as error:
        parse_raw_copyability_signal(payload, frozen_wallets=[WALLET])
    assert error.value.code == "GEN4_COPYABILITY_RAW_NON_SOL_QUOTE_ASSET_DELTA"
    assert error.value.evidence["non_sol_quote_asset_deltas_raw"][USDC_MINT] == -75_144_064


def test_m82_rejects_tiny_native_delta_even_without_stablecoin_delta():
    payload = _payload(native_delta=-150_000, fee=100_000)
    with pytest.raises(CanonicalParserGen4CopyabilityError) as error:
        parse_raw_copyability_signal(payload, frozen_wallets=[WALLET])
    assert error.value.code == "GEN4_COPYABILITY_RAW_NOT_SOL_PAIRED_BUY"
    assert error.value.evidence["net_spent_lamports"] == 50_000
    assert error.value.evidence["minimum_net_spent_lamports"] == 1_000_000


def test_m82_still_accepts_material_native_sol_buy():
    signal = parse_raw_copyability_signal(
        _payload(native_delta=-10_100_000, fee=100_000),
        frozen_wallets=[WALLET],
    )
    assert signal.side == "BUY"
    assert signal.sol_equivalent_delta_lamports == -10_100_000
    assert signal.wallet_effective_price_sol == pytest.approx(0.01)


def test_m82_still_accepts_material_existing_wsol_buy():
    payload = _payload(native_delta=-100_000, fee=100_000)
    payload["meta"]["preTokenBalances"].append(
        _balance(WALLET, SOL_MINT, 50_000_000, 9)
    )
    payload["meta"]["postTokenBalances"].append(
        _balance(WALLET, SOL_MINT, 40_000_000, 9)
    )
    signal = parse_raw_copyability_signal(payload, frozen_wallets=[WALLET])
    assert signal.side == "BUY"
    assert signal.sol_equivalent_delta_lamports == -10_100_000
    assert signal.wallet_effective_price_sol == pytest.approx(0.01)


def test_m82_discovery_is_deterministic_and_excludes_known_wallets():
    token_a = "78RQLrHGyj8hw3c66PvmM9gxC11HueNA9ggUFAkEpump"
    token_b = "Gyd3vTreguB9gLDk4X5i6z3mq8RX86TwdSTEewC5pump"
    other = "7rsS3H2VN5SmGc5jU5TWVMuzz3xqj5LWGeNzSfkSCEKJ"

    def row(wallet: str, signature: str, block_time: int):
        return {
            "blockTime": block_time,
            "transaction": {
                "signatures": [signature],
                "message": {
                    "accountKeys": [
                        {"pubkey": wallet, "signer": True},
                        {"pubkey": "11111111111111111111111111111111", "signer": False},
                    ]
                },
            },
        }

    candidates = discover_candidates(
        {
            token_a: [row(WALLET, "a", 10), row(other, "b", 9)],
            token_b: [row(WALLET, "c", 11)],
        },
        excluded_wallets={other},
        limit=10,
    )
    assert [item["wallet_address"] for item in candidates] == [WALLET]
    assert candidates[0]["m82_discovery_evidence"]["token_overlap_count"] == 2
    assert candidates[0]["m82_discovery_evidence"]["transaction_occurrences"] == 2


def test_m82_seed_token_merge_prefers_repeated_evidence():
    token_a = "78RQLrHGyj8hw3c66PvmM9gxC11HueNA9ggUFAkEpump"
    token_b = "Gyd3vTreguB9gLDk4X5i6z3mq8RX86TwdSTEewC5pump"
    m66 = {
        "seed_tokens": [
            {
                "token_mint": token_a,
                "seed_swap_occurrences": 4,
                "latest_seed_swap_timestamp": 100,
            },
            {
                "token_mint": token_b,
                "seed_swap_occurrences": 1,
                "latest_seed_swap_timestamp": 90,
            },
        ]
    }
    m81 = {
        "discovery_candidates": [
            {
                "m66_discovery_evidence": {
                    "token_overlap": [token_a],
                    "token_history_occurrences": 3,
                    "latest_token_history_timestamp": 110,
                }
            }
        ]
    }
    selected = select_discovery_tokens(m66, m81, limit=2)
    assert [item["token_mint"] for item in selected] == [token_a, token_b]


def test_m82_credit_contract_is_hard_bounded():
    assert M82_GTFA_CREDITS_PER_REQUEST == 50
    assert M82_MAX_RPC_CREDITS == 9_000
    assert M82_MAX_RPC_CREDITS % M82_GTFA_CREDITS_PER_REQUEST == 0


def test_m82_global_helius_credit_mapping_counts_gtfa_at_provider_cost():
    assert helius_rpc_credit_cost("getTransactionsForAddress") == 50
    assert helius_rpc_credit_cost("getTransfersByAddress") == 10
    assert helius_rpc_credit_cost("getTransaction") == 1


def _load_runner_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_m82_paid_rpc_sprint.py"
    spec = importlib.util.spec_from_file_location("m82_runner_test_module", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_m82_gtfa_client_reserves_50_once_and_resume_hits_cache(tmp_path, monkeypatch):
    runner = _load_runner_module()
    reservations = []
    network = []

    def fake_reserve(**kwargs):
        reservations.append(dict(kwargs))
        return {"enforced": True}

    class Response:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {
                "jsonrpc": "2.0",
                "id": "m82",
                "result": {
                    "data": [],
                    "paginationToken": None,
                },
            }

    def fake_post(url, **kwargs):
        network.append((url, kwargs))
        return Response()

    monkeypatch.setattr(runner, "reserve_helius_credits", fake_reserve)
    monkeypatch.setattr(runner.httpx, "post", fake_post)
    monkeypatch.setattr(runner.settings, "HELIUS_API_KEY", "SECRET-MUST-NOT-BE-CACHED")

    state = {
        "schema": runner.STATE_SCHEMA,
        "version": runner.M82_VERSION,
        "scope": runner.M82_SCOPE,
        "status": "RUNNING",
        "started_at_utc": "2026-08-17T16:00:00+00:00",
        "updated_at_utc": "2026-08-17T16:00:00+00:00",
        "history_cutoff_at_utc": "2026-07-17T16:00:00+00:00",
        "input_hashes": {},
        "credits_reserved": 0,
        "network_attempts_reserved": 0,
    }
    state_path = tmp_path / "state.json"
    runner._write_state(state_path, state)
    client = runner.CachedGuardedGtfaClient(
        tmp_path / "cache",
        state=state,
        state_path=state_path,
        effective_total_credit_cap=100,
    )
    config = {
        "transactionDetails": "full",
        "limit": 100,
        "filters": {"status": "succeeded"},
    }

    first = client.call(WALLET, config, origin="TEST_M82")
    second = client.call(WALLET, config, origin="TEST_M82")

    assert first == second == {"data": [], "paginationToken": None}
    assert len(reservations) == 1
    assert reservations[0]["category"] == "RPC"
    assert reservations[0]["estimated_credits"] == 50
    assert len(network) == 1
    assert state["credits_reserved"] == 50
    assert client.stats()["cache_hits_current_process"] == 1
    cache_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "cache" / "entries").glob("*.json")
    )
    assert "SECRET-MUST-NOT-BE-CACHED" not in cache_text


def test_m82_model_policy_stays_inside_m67_contract_for_every_depth():
    for depth in (
        M82_PASS1_TRANSACTIONS,
        M82_PASS2_TRANSACTIONS,
        M82_PASS3_TRANSACTIONS,
    ):
        policy = build_model_policy(depth)
        assert 1 <= int(policy["maximum_deep_wallets"]) <= 3
        assert 30 <= int(policy["public_rpc_request_cap"]) <= 2000
        assert int(policy["maximum_signatures_per_deep_wallet"]) == depth


def test_m82_resume_repair_removes_only_retry_required_rows(tmp_path):
    runner = _load_runner_module()
    state = {
        "schema": runner.STATE_SCHEMA,
        "version": runner.M82_VERSION,
        "scope": runner.M82_SCOPE,
        "status": "RUNNING",
        "started_at_utc": "2026-08-17T16:00:00+00:00",
        "updated_at_utc": "2026-08-17T16:00:00+00:00",
        "history_cutoff_at_utc": "2026-07-17T16:00:00+00:00",
        "input_hashes": {},
        "credits_reserved": 3500,
        "network_attempts_reserved": 70,
        "stage_completed": 6,
        "stage_total": 50,
        "stage_results": {
            "PASS1": {
                WALLET: {
                    "wallet_address": WALLET,
                    "disposition": "RPC_RETRY_REQUIRED",
                    "failure_reasons": ["M67M70ZeroHeliusError:Numero wallet deep fuori contratto."],
                },
                "7rsS3H2VN5SmGc5jU5TWVMuzz3xqj5LWGeNzSfkSCEKJ": {
                    "wallet_address": "7rsS3H2VN5SmGc5jU5TWVMuzz3xqj5LWGeNzSfkSCEKJ",
                    "disposition": "RESEARCH_ONLY",
                },
            }
        },
    }
    path = tmp_path / "state.json"
    runner._write_state(path, state)
    removed = runner._repair_retry_rows_for_resume(path, state)
    assert removed == [f"PASS1:{WALLET}"]
    assert WALLET not in state["stage_results"]["PASS1"]
    assert "7rsS3H2VN5SmGc5jU5TWVMuzz3xqj5LWGeNzSfkSCEKJ" in state["stage_results"]["PASS1"]
    assert state["credits_reserved"] == 3500
    assert state["network_attempts_reserved"] == 70
    assert runner.M82_RESUME_HOTFIX in state["runtime_hotfixes"]


def test_m82_checkpoint_writes_are_serialized(tmp_path, monkeypatch):
    runner = _load_runner_module()
    active = 0
    maximum_active = 0
    guard = threading.Lock()

    def fake_atomic(path, payload):
        nonlocal active, maximum_active
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.01)
        with guard:
            active -= 1
        path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(runner, "write_json_atomic", fake_atomic)
    state = {"counter": 0}
    path = tmp_path / "state.json"

    threads = [
        threading.Thread(target=runner._write_state, args=(path, state))
        for _ in range(20)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert maximum_active == 1


def test_m82_stale_tmp_is_removed_only_when_identical(tmp_path):
    runner = _load_runner_module()
    path = tmp_path / "state.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.write_text('{"ok":1}', encoding="utf-8")
    tmp.write_text('{"ok":1}', encoding="utf-8")
    assert runner._cleanup_stale_state_tmp(path) is True
    assert not tmp.exists()

    tmp.write_text('{"ok":2}', encoding="utf-8")
    with pytest.raises(runner.M82PaidRpcSprintError, match="M82_STALE_TMP_DIFFERS_FROM_STATE"):
        runner._cleanup_stale_state_tmp(path)
