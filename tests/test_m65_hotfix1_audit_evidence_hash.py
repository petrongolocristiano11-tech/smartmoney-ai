from __future__ import annotations

import copy

import pytest

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from scripts.reissue_m64_hashfixed_audit_report import (
    M65HashReissueError,
    repair_enriched_trade_hashes,
)


def _trade(*, legacy_bug: bool) -> dict:
    scenario = {
        "model_scenario": "net_policy",
        "entry_signature": "hotfix1-entry-full-signature",
        "last_exit_signature": "hotfix1-exit-full-signature",
        "token_mint": "Hotfix1SanitizedTokenMint",
        "closed_at": "2026-08-13T14:08:43+00:00",
        "pnl_lamports": -745_684,
        "cost_lamports": 10_100_000,
        "fee_lamports": 200_000,
        "return_percent": -7.3830099,
    }
    scenario_hash = canonical_sha256(scenario)
    enriched = {
        **scenario,
        "cost_impact": {
            "slippage_impact_lamports": 312_000,
            "fee_impact_lamports": 200_000,
            "total_cost_impact_lamports": 512_000,
            "interaction_lamports": 0,
            "method": "FOUR_SCENARIO_SAME_TRANSACTION_PROXY",
        },
    }
    if legacy_bug:
        enriched["evidence_sha256"] = scenario_hash
        enriched["evidence_sha256"] = canonical_sha256(enriched)
    else:
        enriched["evidence_sha256"] = canonical_sha256(enriched)
    return enriched


def _report(trade: dict) -> dict:
    official = []
    for index in range(83):
        row = {
            "entry_signature": f"official-{index:03d}",
            "pnl_lamports": index,
        }
        row["evidence_sha256"] = canonical_sha256(row)
        official.append(row)
    reconstructed = [copy.deepcopy(trade) for _ in range(17)]
    for index, row in enumerate(reconstructed):
        row["entry_signature"] = f"reconstructed-{index:03d}"
        scenario = {
            key: value
            for key, value in row.items()
            if key not in {"evidence_sha256", "cost_impact"}
        }
        legacy_payload = {
            key: value for key, value in row.items() if key != "evidence_sha256"
        }
        legacy_payload["evidence_sha256"] = canonical_sha256(scenario)
        row["evidence_sha256"] = canonical_sha256(legacy_payload)
    return {
        "samples": {
            "official_realtime": {"trades": official},
            "reconstructed": {"trades": reconstructed},
            "cutoff_complete_batch_sensitivity": {"supplemental_trades": []},
        }
    }


def test_known_nested_hash_bug_is_repaired_without_changing_economics():
    report = _report(_trade(legacy_bug=True))
    original = copy.deepcopy(report)
    fixed, counts = repair_enriched_trade_hashes(report)

    assert counts["official_valid_count"] == 83
    assert counts["repaired_enriched_trade_count"] == 17
    for before, after in zip(
        original["samples"]["reconstructed"]["trades"],
        fixed["samples"]["reconstructed"]["trades"],
    ):
        assert {
            key: value for key, value in before.items() if key != "evidence_sha256"
        } == {
            key: value for key, value in after.items() if key != "evidence_sha256"
        }
        assert after["evidence_sha256"] == canonical_sha256(
            {
                key: value
                for key, value in after.items()
                if key != "evidence_sha256"
            }
        )


def test_unknown_hash_mismatch_is_rejected_fail_closed():
    report = _report(_trade(legacy_bug=True))
    report["samples"]["reconstructed"]["trades"][0][
        "evidence_sha256"
    ] = "f" * 64

    with pytest.raises(M65HashReissueError, match="non corrisponde al difetto noto"):
        repair_enriched_trade_hashes(report)
