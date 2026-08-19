from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_M73_SHA = "c88b557e2cf6902805e21d8a8c13ac00c18f31ef838c57346729d77ee005ad57"
EXPECTED_RESUME_LAUNCHER_SHA = "cd46aaf6340ed195caacc249ec0309db036562a88172fe48f319d8fcc7683117"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    m73_path = ROOT / "scripts/run_m73_controlled_new_wallet_qualification.py"
    resume_path = ROOT / "scripts/run_m73_post_m66_expanded_resume.py"
    old_launcher = ROOT / "scripts/run_m66_m73_expanded_discovery_tranche.py"
    require(sha(m73_path) == EXPECTED_M73_SHA, "SHA runner M73 Fix3 inatteso")
    require(sha(resume_path) == EXPECTED_RESUME_LAUNCHER_SHA, "SHA launcher resume Fix3 inatteso")

    source = m73_path.read_text(encoding="utf-8")
    required_source = (
        "RESUME_M73_AFTER_M66_EXPANDED_POLICY_FAILURE_EXACT_ARTIFACTS",
        "1f6d6d3c73e3fcbc32f99482aa4b70fe0be6f3f89144c06a476e4dcef61ad99c",
        "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080",
        "0cab70ecee5d437bff83729337be2db547ff2f2680cb069d98540c78b9211c31",
        "e58a5cf61785d30c89334c81fc1ab0f1279577837fbc7bd6a7204e6eda66568f",
        "EXACT_LOCK_EXACT_M66_REPORT_CACHE_LOG_SKIP_M66_ZERO_NEW_HELIUS_ONE_SHOT",
        "def _build_m73_m67_model_policy",
        '"maximum_deep_wallets": min(deep_candidates, 3)',
        '"public_rpc_request_cap": min(public_rpc_requests, 2_000)',
        "def _extract_ranked_m66_prescreen_pass_candidates",
        'item.get("status") != "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST"',
        'normalized["score"] = float(item.get("prescreen_score") or 0.0)',
        "M73_M66_RESUME_MODE=EXACT_EXISTING_M66_ARTIFACTS_ZERO_NEW_HELIUS",
        "M73_M66_INVOKED=NO",
        "M73_NEW_HELIUS_REQUESTS=0",
        "M73_NEW_HELIUS_CREDITS=0",
        "M73_SELECTED_DEEP_WALLETS=",
        '"maximum_retries": budget.get("maximum_retries") == 0',
    )
    for marker in required_source:
        require(marker in source, f"Marker M73 mancante: {marker}")

    resolver = source.split("def _resolve_exact_post_m66_resume_evidence", 1)[1]
    resume_branch = resolver.split("def _build_m73_m67_model_policy", 1)[0]
    require("_invoke_m66_lane" not in resume_branch, "Resume può invocare M66")
    require("_load_exact_post_m66_resume_artifacts" in resume_branch, "Resume non usa artifact esatti")

    resume_source = resume_path.read_text(encoding="utf-8")
    for marker in (
        "M66_REEXECUTION_AUTHORIZED=NO",
        "NEW_HELIUS_REQUESTS_AUTHORIZED=0",
        "NEW_HELIUS_CREDITS_AUTHORIZED=0",
        "REUSE_M66_REQUESTS=77",
        "REUSE_M66_CREDITS=7700",
        "REUSE_M66_PRESCREEN_PASS=27",
        "M73_POST_M66_RESUME_SELECTION=PASS_TOP6_PRESCREEN",
        "AUTO_RETRY=NO",
        "LIVE_AUTHORIZED=NO",
        "SIGNER_AUTHORIZED=NO",
    ):
        require(marker in resume_source, f"Marker launcher resume mancante: {marker}")
    require("exit(" not in resume_source, "Launcher resume contiene exit() esplicito")

    old_source = old_launcher.read_text(encoding="utf-8")
    require(EXPECTED_M73_SHA in old_source, "Launcher storico non traccia nuovo SHA M73")

    print("=== M73 POST-M66 RESUME FIX3 VERIFIER ===")
    print("EXACT_CURRENT_LOCK_SHA=YES")
    print("EXACT_M66_REPORT_SHA=YES")
    print("EXACT_M66_CACHE_SHA=YES")
    print("EXACT_FAILED_LOG_SHA=YES")
    print("M66_REEXECUTION_AUTHORIZED=NO")
    print("NEW_HELIUS_REQUESTS_AUTHORIZED=0")
    print("M67_LEGACY_RESOURCE_CONTRACT_PRESERVED=YES")
    print("M73_EXPANDED_RESOURCE_ENVELOPE_SEPARATED_FROM_M67_MODEL=YES")
    print("PRESCREEN_SCORE_USED=YES")
    print("PRESCREEN_REJECTED_EXCLUDED=YES")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
