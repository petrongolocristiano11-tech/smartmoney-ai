from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import run_m73_controlled_new_wallet_qualification as runner


def _sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_exact_artifacts(tmp_path: Path, monkeypatch, *, maximum_retries=0):
    report = {
        "scope": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "discovery": "PASS",
        "budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
        "seed_wallet": "F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        "budget": {
            "enhanced_requests_executed": 77,
            "enhanced_credits_reserved_maximum": 7700,
            "enhanced_request_cap": 86,
            "enhanced_credit_cap": 8600,
            "maximum_retries": maximum_retries,
            "cache_hits": 6,
        },
        "candidate_pool": {
            "new_wallets_found_before_limit": 374,
            "wallets_prescreened": 70,
        },
        "summary": {
            "prescreen_pass_needing_full_gen4_history": 27,
        },
        "activation": {
            "micro_live_execution_authorized": False,
            "signer_authorized": False,
        },
        "candidate_results": [],
    }
    report_bytes = (json.dumps(report, sort_keys=True) + "\n").encode("utf-8")
    cache_bytes = b'{"cache":"exact"}\n'
    log_bytes = b'exact failed expanded run\n'

    report_name = "m66-report.json"
    cache_name = "m66-cache.json"
    log_name = "expanded-failed.txt"
    (tmp_path / report_name).write_bytes(report_bytes)
    (tmp_path / cache_name).write_bytes(cache_bytes)
    (tmp_path / log_name).write_bytes(log_bytes)

    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_NAME", report_name)
    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_SHA256", _sha_bytes(report_bytes))
    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_NAME", cache_name)
    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_SHA256", _sha_bytes(cache_bytes))
    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_NAME", log_name)
    monkeypatch.setattr(runner, "M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_SHA256", _sha_bytes(log_bytes))
    return report


def test_exact_resume_validator_accepts_literal_zero_maximum_retries(tmp_path, monkeypatch):
    expected = _write_exact_artifacts(tmp_path, monkeypatch, maximum_retries=0)
    artifacts = runner._load_exact_post_m66_resume_artifacts(tmp_path)
    assert artifacts["report"] == expected
    assert artifacts["report"]["budget"]["maximum_retries"] == 0


def test_exact_resume_validator_rejects_nonzero_maximum_retries(tmp_path, monkeypatch):
    _write_exact_artifacts(tmp_path, monkeypatch, maximum_retries=1)
    with pytest.raises(runner.M73ControlledQualificationError, match="maximum_retries"):
        runner._load_exact_post_m66_resume_artifacts(tmp_path)
