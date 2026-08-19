from __future__ import annotations

from pathlib import Path

from backend.app.services.gen4_paid_candidate_economic_triage_service import (
    M79_EXPECTED_REMAINING,
    M79_PASS1_SIGNATURES,
    M79_PASS2_SIGNATURES,
    M79_PASS2_WALLETS,
    M79_PUBLIC_RPC_REQUEST_CAP,
    build_final_report,
    build_model_policy,
    extract_paid_remaining_candidates,
    rank_results,
    select_pass2_wallets,
    validate_final_report,
)
from scripts import run_m79_paid_candidate_zero_helius_triage as runner


DEEP = [
    "6onSjcGDusjeU5phv7pDQS5srQBwNcyrd4ntKmeNBySm",
    "BXryySjtoLsVCPeqrhZDj9nHSHkjvpevEpRgBzGa1NRm",
    "EyUe9QvXGbMHAjKisjrb5qaem3dWQVUxhA1DgE2HtnVC",
    "FEnytBSi3X86gAMCqHtsoWHavtiij2hGyuFKPbSNwZAC",
    "TH5KpPyqJ8SBE9Sya7YVzY8217MQGmjrjgG9WusW4M7",
    "2GFVxYeK7JR9mdNFjbqT1tiZkNaK6R386k6Rb7Bvauov",
]
REMAINING = [
    "32YYsqQc59ZTLctaF5gjGYcpcCZzwPFYJsshc4ZwGh9U",
    "FqusXu9MgM4Y9KnZkgN8PVwYW3ev9ufeeaDDG4F6giUB",
    "FzAEvXZaMPwhcf468Ei967sHoe3kVepyxf8v1E1Vy4gG",
    "8zyn2U6uawAtZgMg6jaqkcaUPGniPMpCag3Pqd6TherS",
    "65fVNrzjUvY5F9s2hBo1bxzSBGmtKwzaY5CnMGfeyu1e",
    "2RDozVSBWGJfUZCN39krny7KJyXbAss2fDzvc2NCrUfe",
    "F6GL87CSThFWpaBKPqnkVxYravxfx9Wf9P97TqTCyKSY",
    "5z8G38NMcLxgJtNxC4J64u4mzUNJnCXg5zVTgoAGPRXh",
    "3TtPbXMcBZghb7GPXqhk83w41Mo2uB4fmgtyoHJJ7Upe",
    "8bjdSHWUUHv8Rg4BbwZh8go1amPghZYw8Lr9BZCyyjM5",
    "9MctBmGwpYLeubobAGLXAgXc4eUjR71u9pAg9Ep6oW5F",
    "MUsUt3S1hKy5NdS7QnzPSRPuBALG9PQkakhkg4L1aXc",
    "5Nz2NSefJtU9QSFo3RVa3r73BnpoT82F5kpBN58Yk99u",
    "EHxRVsfxXMV357tCR3HTm3K9636GEPfuTEkQ8Pkii12V",
    "8X8a8aEDPx8Uv3EEmMHJnUJPyXc23iTsLy7Zd1nE5R5",
    "8MDaZgS4Virv9P7ph4Nvxzi9TP7HebQ1eV4PcqBUnxQS",
    "5znvhmUXPqy5kx2KEH4aPvCuA52wgaaKUxZCrZqPx1u6",
    "EPCxJukKMUKx95Kuv5jyGjPCSoqGqRBSUnessaHbvY5v",
    "Bh4gz6prg2m7kTsfuJczh7rxtE7wtHCbH2vk9NFymQVu",
    "28FjWowLVSQCgKtDRXSkdrorpWbE75pWwSBakvfR6tkR",
    "FVeneEoiAUJrGZPgP54MAu6eYDh3gNDVu6DUUxRyeZYE",
]


def _reports():
    all_wallets = DEEP + REMAINING
    m66 = {
        "scope": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "candidate_results": [
            {
                "wallet_address": wallet,
                "status": "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST",
                "prescreen_score": 100.0 - index / 100.0,
                "sample": {"valid_swaps": 50 + index},
                "discovery_evidence": {},
            }
            for index, wallet in enumerate(all_wallets)
        ],
    }
    m73 = {
        "scope": "M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION",
        "evaluation": "PASS",
        "candidate_results": [{"wallet_address": wallet} for wallet in DEEP],
    }
    return m66, m73


def _result(wallet: str, *, tier: int, checks: int, pf: float, net: float, prescreen: float):
    return {
        "wallet_address": wallet,
        "priority_tier": tier,
        "core_checks_passed": checks,
        "transaction_completeness_percent": 100.0,
        "prescreen_score": prescreen,
        "economic_score": 70.0,
        "net_pnl_without_best_trade_sol": net / 2,
        "metrics": {
            "closed_trade_count": 40,
            "profit_factor": pf,
            "net_pnl_sol": net,
            "win_rate_percent": 55.0,
            "maximum_drawdown_percent": 8.0,
        },
        "recent_metrics": {"profit_factor": pf, "net_pnl_sol": max(net, 0.0)},
    }


def test_exact_paid_remaining_set_is_21_and_excludes_deep_six():
    m66, m73 = _reports()
    result = extract_paid_remaining_candidates(m66, m73)
    assert len(result) == M79_EXPECTED_REMAINING == 21
    assert {item["wallet_address"] for item in result} == set(REMAINING)
    assert not ({item["wallet_address"] for item in result} & set(DEEP))


def test_model_policy_preserves_gen4_and_only_changes_signature_depth():
    first = build_model_policy(maximum_signatures=M79_PASS1_SIGNATURES)
    second = build_model_policy(maximum_signatures=M79_PASS2_SIGNATURES)
    for policy in (first, second):
        assert policy["starting_capital_sol"] == 1.0
        assert policy["fixed_buy_size_sol"] == 0.05
        assert policy["slippage_bps"] == 100
        assert policy["fee_bps"] == 10
        assert policy["copy_delay_seconds"] == 8
        assert policy["maximum_deep_wallets"] == 3
        assert policy["public_rpc_request_cap"] == 2000
    assert first["maximum_signatures_per_deep_wallet"] == 60
    assert second["maximum_signatures_per_deep_wallet"] == 150


def test_economics_outrank_prescreen_score():
    weak_100 = _result("weak", tier=0, checks=3, pf=0.6, net=-0.2, prescreen=100.0)
    strong_85 = _result("strong", tier=3, checks=12, pf=1.8, net=0.15, prescreen=85.0)
    ranked = rank_results([weak_100, strong_85])
    assert ranked[0]["wallet_address"] == "strong"
    assert ranked[1]["wallet_address"] == "weak"


def test_pass2_selection_is_exactly_eight_and_deterministic():
    rows = [
        _result(
            f"wallet-{index:02d}",
            tier=3 if index < 4 else 2,
            checks=12 - (index % 3),
            pf=2.0 - index / 100.0,
            net=0.2 - index / 1000.0,
            prescreen=80.0 + index,
        )
        for index in range(21)
    ]
    first = select_pass2_wallets(rows)
    second = select_pass2_wallets(list(reversed(rows)))
    assert first == second
    assert len(first) == M79_PASS2_WALLETS == 8
    assert len(set(first)) == 8


def test_nominal_two_pass_request_plan_fits_hard_cap():
    # PASS1: 21 * (1 signature page + 60 transactions) = 1281.
    # PASS2: the first page and first 60 tx are cached; each of 8 wallets adds
    # 1 signature page + 90 transactions = 728. Total nominal = 2009.
    nominal = (21 * (1 + 60)) + (8 * (1 + 90))
    assert nominal == 2009
    assert nominal < M79_PUBLIC_RPC_REQUEST_CAP == 2600


def test_final_report_never_promotes_or_authorizes_live():
    pass1 = [
        _result(f"p1-{i:02d}", tier=2, checks=8, pf=1.3, net=0.02, prescreen=90)
        for i in range(21)
    ]
    pass2 = [
        _result(f"p2-{i:02d}", tier=3, checks=12, pf=1.6, net=0.05, prescreen=85)
        for i in range(8)
    ]
    m73 = {
        "candidate_results": [],
    }
    report = build_final_report(
        m66_report_sha256="a" * 64,
        m73_report_sha256="b" * 64,
        base_cache_sha256="c" * 64,
        delta_cache_sha256="d" * 64,
        started_at_utc="2026-08-16T19:00:00+00:00",
        completed_at_utc="2026-08-16T20:00:00+00:00",
        pass1_results=pass1,
        pass2_results=pass2,
        pass2_selected=[row["wallet_address"] for row in pass2],
        m73_report=m73,
        rpc_stats={"requests": 2000, "cache_hits": 500, "retry_429": 0},
    )
    validate_final_report(report)
    assert report["strategy"]["promotion_from_triage_allowed"] is False
    assert report["safety"]["helius_requests"] == 0
    assert report["safety"]["helius_credits"] == 0
    assert report["safety"]["live_orders"] == 0
    assert report["safety"]["signer_authorized"] is False
    assert report["safety"]["micro_live_execution_authorized"] is False
    assert len(report["recommended_next_deep_wallets"]) == 6


def test_delta_cache_only_contains_new_entries(tmp_path: Path):
    base = {
        "schema": "SMARTMONEY_M67_ZERO_HELIUS_PUBLIC_RPC_CACHE_V1",
        "public_origin": "https://api.mainnet-beta.solana.com",
        "entries": {"base": {"request": {}, "result": None, "result_sha256": "x"}},
    }
    merged = {
        **base,
        "entries": {
            **base["entries"],
            "delta": {"request": {}, "result": None, "result_sha256": "y"},
        },
    }
    # This helper does not inspect result hashes; it only separates base keys.
    path = tmp_path / "delta.json"
    runner._write_delta_cache(
        merged_cache=merged,
        base_keys={"base"},
        delta_path=path,
    )
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    assert set(value["entries"]) == {"delta"}


def test_runner_contains_no_helius_endpoint_or_api_key_dependency():
    source = Path(runner.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "api.helius" not in lowered
    assert "helius-rpc" not in lowered
    assert "helius_api_key" not in lowered
    assert "get_wallet_history" not in source
    assert 'PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"' in source
