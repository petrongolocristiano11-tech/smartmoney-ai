from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_DEFAULT_POLICY,
    M67M70ZeroHeliusError,
    validate_policy as validate_m67_policy,
)
from scripts import run_m73_controlled_new_wallet_qualification as m73_runner


def _limits(**overrides):
    value = {
        "helius_requests": 90,
        "helius_credits": 9000,
        "helius_retries": 0,
        "public_rpc_requests": 4000,
        "deep_candidates": 6,
        "signatures_per_candidate": 500,
    }
    value.update(overrides)
    return value


def test_legacy_m67_contract_remains_3_deep_and_2000_rpc():
    with pytest.raises(M67M70ZeroHeliusError, match="Numero wallet deep"):
        validate_m67_policy({
            **M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": 6,
            "public_rpc_request_cap": 4000,
        })
    with pytest.raises(M67M70ZeroHeliusError, match="Cap RPC pubblico"):
        validate_m67_policy({
            **M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": 3,
            "public_rpc_request_cap": 4000,
        })


def test_m73_model_policy_keeps_m67_resource_fields_legacy_safe_while_limits_expand():
    limits = _limits()
    policy = m73_runner._build_m73_m67_model_policy(limits)
    assert limits["deep_candidates"] == 6
    assert limits["public_rpc_requests"] == 4000
    assert policy["maximum_deep_wallets"] == 3
    assert policy["public_rpc_request_cap"] == 2000
    assert policy["maximum_signatures_per_deep_wallet"] == 500
    assert policy["starting_capital_sol"] == 1.0
    assert policy["fixed_buy_size_sol"] == 0.05
    assert policy["slippage_bps"] == 100
    assert policy["fee_bps"] == 10
    assert policy["copy_delay_seconds"] == 8
    assert policy["maximum_open_positions"] == 5


def test_m73_model_policy_accepts_exact_m73_hard_max_but_stays_m67_valid():
    limits = _limits(deep_candidates=8, public_rpc_requests=5000)
    policy = m73_runner._build_m73_m67_model_policy(limits)
    assert limits["deep_candidates"] == 8
    assert limits["public_rpc_requests"] == 5000
    assert policy["maximum_deep_wallets"] == 3
    assert policy["public_rpc_request_cap"] == 2000


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("deep_candidates", 9, "candidati deep"),
        ("public_rpc_requests", 5001, "Cap RPC pubblico"),
        ("signatures_per_candidate", 501, "Firme per candidato"),
    ],
)
def test_m73_adapter_fails_closed_beyond_expanded_bounds(field, value, message):
    limits = _limits(**{field: value})
    with pytest.raises(m73_runner.M73ControlledQualificationError, match=message):
        m73_runner._build_m73_m67_model_policy(limits)


def test_runtime_launcher_hash_contract_tracks_patched_m73_runner():
    root = Path(__file__).resolve().parents[1]
    runner_path = root / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    launcher_source = (
        root / "scripts" / "run_m66_m73_expanded_discovery_tranche.py"
    ).read_text(encoding="utf-8")
    digest = hashlib.sha256(runner_path.read_bytes()).hexdigest()
    assert digest == "c88b557e2cf6902805e21d8a8c13ac00c18f31ef838c57346729d77ee005ad57"
    assert f'"scripts/run_m73_controlled_new_wallet_qualification.py": "{digest}"' in launcher_source
