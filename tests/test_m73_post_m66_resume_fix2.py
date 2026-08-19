from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67_service
from scripts import run_m73_controlled_new_wallet_qualification as runner


WALLETS = [
    "6onSjcGDusjeU5phv7pDQS5srQBwNcyrd4ntKmeNBySm",
    "BXryySjtoLsVCPeqrhZDj9nHSHkjvpevEpRgBzGa1NRm",
    "EyUe9QvXGbMHAjKisjrb5qaem3dWQVUxhA1DgE2HtnVC",
    "FEnytBSi3X86gAMCqHtsoWHavtiij2hGyuFKPbSNwZAC",
    "TH5KpPyqJ8SBE9Sya7YVzY8217MQGmjrjgG9WusW4M7",
    "2GFVxYeK7JR9mdNFjbqT1tiZkNaK6R386k6Rb7Bvauov",
    "26b966MheUKjyRTes8vLbpH1qV6pVY7cNzAiyZuyrB9W",
]


def _report() -> dict:
    scores = [100.0, 100.0, 100.0, 100.0, 100.0, 99.7917]
    rows = [
        {
            "wallet_address": wallet,
            "status": "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST",
            "prescreen_score": score,
        }
        for wallet, score in zip(WALLETS[:6], scores)
    ]
    rows.append(
        {
            "wallet_address": WALLETS[6],
            "status": "PRESCREEN_REJECTED",
            "prescreen_score": 1000.0,
        }
    )
    return {
        "scope": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "discovery": "PASS",
        "budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
        "seed_wallet": "F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        "budget": {
            "enhanced_requests_executed": 77,
            "enhanced_credits_reserved_maximum": 7700,
            "enhanced_request_cap": 86,
            "enhanced_credit_cap": 8600,
            "maximum_retries": 0,
            "cache_hits": 6,
        },
        "candidate_pool": {
            "new_wallets_found_before_limit": 374,
            "wallets_prescreened": 70,
        },
        "summary": {
            "prescreen_pass_needing_full_gen4_history": 6,
        },
        "activation": {
            "micro_live_execution_authorized": False,
            "signer_authorized": False,
        },
        "candidate_results": rows,
    }


def _write(path: Path, payload: bytes) -> str:
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def test_ranked_extraction_uses_prescreen_score_and_excludes_rejected():
    rows = runner._extract_ranked_m66_prescreen_pass_candidates(
        _report(), excluded_wallets=set(), maximum_candidates=80
    )
    assert len(rows) == 6
    assert all(item["wallet_address"] != WALLETS[6] for item in rows)
    assert [item["prescreen_score"] for item in rows] == sorted(
        [item["prescreen_score"] for item in rows], reverse=True
    )
    assert rows[0]["prescreen_score"] == 100.0
    assert rows[-1]["prescreen_score"] == 99.7917


def test_model_policy_survives_m67_internal_revalidation_at_expanded_m73_limits():
    limits = {
        "helius_requests": 90,
        "helius_credits": 9000,
        "helius_retries": 0,
        "public_rpc_requests": 4000,
        "deep_candidates": 6,
        "signatures_per_candidate": 500,
    }
    policy = runner._build_m73_m67_model_policy(limits)
    assert policy["maximum_deep_wallets"] == 3
    assert policy["public_rpc_request_cap"] == 2000
    # simulate_gen4_from_public_events performs validate_policy() internally.
    result = m67_service.simulate_gen4_from_public_events([], policy=policy)
    assert result["metrics"]["closed_trade_count"] == 0


def test_exact_post_m66_lock_recovery_is_one_shot_and_authorizes_zero_new_helius(
    tmp_path, monkeypatch
):
    fixture = Path("tests/fixtures/m73_post_m66_expanded_policy_failure_current_lock.json")
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    lock.write_bytes(fixture.read_bytes())
    assert runner._sha256(lock) == runner.M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256

    report_path = tmp_path / "report.json"
    cache_path = tmp_path / "cache.json"
    log_path = tmp_path / "run.txt"
    monkeypatch.setattr(
        runner,
        "_load_exact_post_m66_resume_artifacts",
        lambda _output_dir: {
            "report_path": report_path,
            "cache_path": cache_path,
            "log_path": log_path,
            "report": _report(),
        },
    )

    started = datetime(2026, 8, 16, 16, 40, tzinfo=timezone.utc)
    _, payload = runner._prepare_execution_lock(
        lock,
        output_dir=tmp_path,
        m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        recovery_confirmation=runner.M73_POST_M66_EXPANDED_POLICY_FAILURE_RECOVERY_CONFIRMATION,
        started=started,
    )
    assert payload["post_m66_expanded_policy_failure_recovery_used"] is True
    assert payload["new_helius_requests_authorized"] == 0
    assert payload["new_helius_credits_authorized"] == 0
    assert payload["state"] == "RECOVERING_M73_FROM_EXACT_M66_ARTIFACTS_AFTER_EXPANDED_POLICY_FAILURE"

    with pytest.raises(runner.M73ControlledQualificationError):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_POST_M66_EXPANDED_POLICY_FAILURE_RECOVERY_CONFIRMATION,
            started=started,
        )


def test_resume_evidence_path_does_not_invoke_m66(tmp_path, monkeypatch):
    report_path = tmp_path / "report.json"
    cache_path = tmp_path / "cache.json"
    log_path = tmp_path / "run.txt"
    monkeypatch.setattr(
        runner,
        "_load_exact_post_m66_resume_artifacts",
        lambda _output_dir: {
            "report_path": report_path,
            "cache_path": cache_path,
            "log_path": log_path,
            "report": _report(),
        },
    )
    monkeypatch.setattr(
        runner,
        "_invoke_m66_lane",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("M66 must not run")),
    )
    monkeypatch.setattr(runner, "known_m72_wallets", lambda _report: set())

    accounting, paths, discovered = runner._resolve_exact_post_m66_resume_evidence(
        output_dir=tmp_path,
        m72_report={},
    )
    assert accounting["new_helius_requests"] == 0
    assert accounting["new_helius_credits"] == 0
    assert paths == [report_path, cache_path]
    assert len(discovered) == 6
