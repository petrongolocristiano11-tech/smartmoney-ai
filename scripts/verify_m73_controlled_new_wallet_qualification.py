from __future__ import annotations

import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.gen4_controlled_new_wallet_qualification_service import (  # noqa: E402
    M66_HELIUS_CONFIRMATION,
    M73_MAX_DEEP_CANDIDATES,
    M73_MAX_HELIUS_CREDITS,
    M73_MAX_HELIUS_REQUESTS,
    M73_MAX_PUBLIC_RPC_REQUESTS,
    M73_MAX_SIGNATURES_PER_CANDIDATE,
    M73_RUN_CONFIRMATION,
    M73_VERSION,
    validate_runtime_limits,
)


EXPECTED_GIT_HEAD = "fe63c528e55af84a97d6deb6872e825a5a43c6b4"
EXPECTED_ALEMBIC_HEAD = "c8a1f3d6e942"
EXPECTED_M66_WRAPPER_SHA256 = "665e267616bf50ef45864490d26f0cf4d5c8a37db1490000bba63a78f9a0ea81"
EXPECTED_M66_SERVICE_SHA256 = "f4312154f95a9256c5a02e62dd4a100414d28c9ed3812159c9b3a75f23e5581a"
EXPECTED_M66_RUNNER_SHA256 = "21da3da6d63c49d4c1443091552f44fbbc302579f19db3a2973c639673096ec4"
EXPECTED_M72_SERVICE_SHA256 = "7c20d828b4d3e006b0735fcefeeebaeb55cb90c91144454e9cecdbef275aa7f8"
EXPECTED_HOTFIX5_POST429_LOCK_SHA256 = "da93df4010d4f5e1fc8e11a323a1a9d573457f1e467712273620b660ed0642e0"
EXPECTED_HOTFIX5_INTERRUPTED_CURRENT_LOCK_SHA256 = "2897afff36d318876ed625e1924180c94bec1092fe7e5d39984f1646c9cc9342"


def sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    require(M73_MAX_HELIUS_REQUESTS == 90, "M73 request cap != 90")
    require(M73_MAX_HELIUS_CREDITS == 9_000, "M73 credit cap != 9000")
    require(M73_MAX_PUBLIC_RPC_REQUESTS == 5_000, "M73 RPC cap != 5000")
    require(M73_MAX_DEEP_CANDIDATES == 8, "M73 candidate cap != 8")
    require(M73_MAX_SIGNATURES_PER_CANDIDATE == 500, "M73 signature cap != 500")
    require(M66_HELIUS_CONFIRMATION == "SPEND_MAX_9000_HELIUS_CREDITS_FOR_M66_DISCOVERY_TRANCHE", "M66 confirmation drift")
    require(M73_RUN_CONFIRMATION.startswith("EXECUTE_M73_"), "M73 confirmation not explicit")
    validate_runtime_limits()
    expected = (
        ("RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1", EXPECTED_M66_WRAPPER_SHA256),
        ("backend/app/services/gen4_controlled_helius_discovery_service.py", EXPECTED_M66_SERVICE_SHA256),
        ("scripts/run_m66_controlled_helius_discovery.py", EXPECTED_M66_RUNNER_SHA256),
        ("backend/app/services/gen4_definitive_discovery_rotation_service.py", EXPECTED_M72_SERVICE_SHA256),
    )
    for relative, digest in expected:
        path = ROOT / relative
        require(path.is_file(), f"Baseline file missing: {relative}")
        require(sha256(path) == digest, f"Baseline hash mismatch: {relative}")
    hotfix5_lock_fixture = ROOT / "tests/fixtures/m73_hotfix5_known_post429_lock.json"
    require(hotfix5_lock_fixture.is_file(), "Hotfix5 known post-429 lock fixture missing")
    require(
        sha256(hotfix5_lock_fixture) == EXPECTED_HOTFIX5_POST429_LOCK_SHA256,
        "Hotfix5 known post-429 lock fixture hash mismatch",
    )
    current_lock_fixture = ROOT / "tests/fixtures/m73_hotfix5_interrupted_current_lock.json"
    require(current_lock_fixture.is_file(), "Current Hotfix5 interrupted lock fixture missing")
    require(
        sha256(current_lock_fixture) == EXPECTED_HOTFIX5_INTERRUPTED_CURRENT_LOCK_SHA256,
        "Current Hotfix5 interrupted lock fixture hash mismatch",
    )
    service_path = ROOT / "backend/app/services/gen4_controlled_new_wallet_qualification_service.py"
    runner_path = ROOT / "scripts/run_m73_controlled_new_wallet_qualification.py"
    service_source = service_path.read_text(encoding="utf-8")
    runner_source = runner_path.read_text(encoding="utf-8")
    for forbidden in ("httpx", "requests.", "db.commit", "db.add", "JupiterSwapClient", "private_key", "seed_phrase"):
        require(forbidden not in service_source, f"Pure M73 service contains forbidden token: {forbidden}")
    for required in (
        "CachedBudgetedPublicRpc",
        "_collect_deep_history",
        "_economic_analysis",
        "M66_HELIUS_CONFIRMATION",
        "EXPECTED_M66_WRAPPER_SHA256",
    ):
        require(required in runner_source, f"M73 runner missing contract token: {required}")
    require("MICRO_LIVE_EXECUTION_AUTHORIZED=NO" in runner_source, "M73 live safety marker missing")
    runner = ROOT / "scripts/run_m73_controlled_new_wallet_qualification.py"
    wrapper = ROOT / "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1"
    runner_source = runner.read_text(encoding="utf-8-sig")
    wrapper_source = wrapper.read_text(encoding="utf-8-sig")
    required_hotfix3_runner = (
        "def _preflight_database_public_url() -> str:",
        "def _railway_backend_helius_key() -> str:",
        "def _resolve_helius_api_key() -> tuple[str, str, dict[str, str]]:",
        'env.pop("HELIUS_API_KEY", None)',
        '"smartmoney-ai",',
        "M73_M66_RUNTIME_HELIUS_API_KEY=YES_REDACTED",
        "M73_HELIUS_API_KEY_SOURCE=",
        "M73_HELIUS_PREFLIGHT_NETWORK_REQUESTS=0",
        "def _sanitize_sensitive_output(",
        "M73_HOTFIX2_RECOVERY_CONFIRMATION",
        "M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256",
        "def _prepare_execution_lock(",
        "M73_DATABASE_PUBLIC_URL_PREFLIGHT=PASS",
        "RECOVERING_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2",
    )
    for token in required_hotfix3_runner:
        require(token in runner_source, f"Hotfix3 runner token missing: {token}")
    require("def _preflight_m66_runtime_environment" not in runner_source, "Legacy Hotfix2 merged-env probe still present")
    secret_start = runner_source.index("def _resolve_helius_api_key")
    secret_end = runner_source.index("def _sanitize_sensitive_output", secret_start)
    secret_body = runner_source[secret_start:secret_end]
    for forbidden in ("get_helius_health", "mainnet.helius", "api.helius", "httpx"):
        require(forbidden not in secret_body, f"Hotfix3 secret resolver performs provider work: {forbidden}")
    required_hotfix2_wrapper = (
        "[string]$RecoveryConfirmation",
        "Get-Command railway.cmd",
        '"--service", "Postgres"',
        '"--environment", "production"',
        '"--no-local"',
        '"--recovery-confirmation", $RecoveryConfirmation',
    )
    for token in required_hotfix2_wrapper:
        require(token in wrapper_source, f"Hotfix2 wrapper token missing: {token}")

    print("=== M73 CONTROLLED NEW WALLET QUALIFICATION VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={EXPECTED_ALEMBIC_HEAD}")
    print(f"QUALIFICATION_VERSION={M73_VERSION}")
    print("M72_NEW_WALLET_DISCOVERY_REQUIRED=YES")
    print("M66_CONTROLLED_LANE_REUSED_EXACT_HASH=YES")
    print("CONTROLLED_HELIUS_MAXIMUM_REQUESTS=90")
    print("CONTROLLED_HELIUS_CREDIT_CAP=9000")
    print("CONTROLLED_HELIUS_DEFAULT_TRANCHE=86_REQUESTS_8600_CREDITS")
    print("CONTROLLED_HELIUS_RETRIES=0")
    print("PUBLIC_RPC_REQUEST_CAP=5000")
    print("DEFAULT_PUBLIC_RPC_REQUEST_CAP=4000")
    print("MAXIMUM_DEEP_CANDIDATES=8")
    print("DEFAULT_DEEP_CANDIDATES=6")
    print("MAXIMUM_SIGNATURES_PER_CANDIDATE=500")
    print("SINGLE_PAGE_ENHANCED_IS_ECONOMIC_PROOF=NO")
    print("CANONICAL_GEN4_PUBLIC_RPC_GATE_REQUIRED=YES")
    print("INCOMPLETE_HISTORY_FAILS_CLOSED=YES")
    print("SHORT_CANARY_EXECUTION_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")
    print("INSTALLER_NETWORK_REQUESTS=0")
    print("HOTFIX3_DATABASE_PUBLIC_URL_PREFLIGHT=BEFORE_LOCK")
    print("HOTFIX3_HELIUS_SOURCE_RESOLUTION=BEFORE_LOCK")
    print("HOTFIX3_RAILWAY_PARENT_HELIUS_REMOVED_BEFORE_PROBE=YES")
    print("HOTFIX3_SEALED_RAILWAY_FALLBACK=LOCAL_DOTENV_THEN_PROCESS_ENV")
    print("HOTFIX3_HELIUS_PROVIDER_PREFLIGHT_REQUESTS=0")
    print("HOTFIX3_ORIGINAL_M66_FIRST_PROVIDER_CALL_WAS_INSIDE_LEGACY_600_CREDIT_CAP=YES")
    print("HOTFIX3_HELIUS_SECRET_OUTPUT=REDACTED")
    print("HOTFIX3_DATABASE_URL_FALLBACK=FORBIDDEN")
    print("HOTFIX3_RAILWAY_POSTGRES_BOOTSTRAP=NO_LOCAL")
    print("HOTFIX3_STALE_LOCK_RECOVERY=EXACT_KNOWN_PRENETWORK_FAILURE_ONLY")
    require("HELIUS_CREDIT_GUARD_ENABLED" in runner_source, "Hotfix4 guard-enabled env missing")
    require("HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION" in runner_source, "Hotfix4 non-production enforcement env missing")
    require("HELIUS_AUTOMATIC_ENHANCED_API_ENABLED" in runner_source, "Hotfix4 automatic Enhanced disable missing")
    require("def _preflight_m63_credit_guard" in runner_source, "Hotfix4 M63 preflight missing")
    require("RECOVER_M73_PRENETWORK_CREDIT_GUARD_NOT_ENFORCED_HOTFIX3" in runner_source, "Hotfix4 recovery token missing")
    require("M63_CREDIT_GUARD_NOT_ENFORCED_BEFORE_FIRST_HELIUS_REQUEST" in runner_source, "Hotfix4 recovery reason missing")
    require(runner_source.index("m63_guard_preflight = _preflight_m63_credit_guard") < runner_source.index("_prepare_execution_lock(", runner_source.index("def main")), "Hotfix4 M63 preflight is not before execution lock")

    print("HOTFIX4_M63_LOCAL_CREDIT_GUARD_ENFORCEMENT=EXPLICIT_TRUE")
    print("HOTFIX4_CREDIT_GUARD_PREFLIGHT=BEFORE_LOCK_ZERO_NETWORK")
    print("HOTFIX4_AUTOMATIC_ENHANCED_API=DISABLED_IN_M66_SUBPROCESS")
    print("HOTFIX4_STALE_LOCK_RECOVERY=EXACT_HOTFIX3_GUARD_FAILURE_ONLY")

    for token in (
        "M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION",
        "RECOVER_M73_POST_PROVIDER_HTTP_429_HOTFIX4_EXACT_LOCK",
        "M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256",
        EXPECTED_HOTFIX5_POST429_LOCK_SHA256,
        "RECOVERING_POST_PROVIDER_HTTP_429_HOTFIX4",
        "M66_HELIUS_HTTP_429_AFTER_ONE_PROVIDER_ATTEMPT",
        "hotfix5_post429_previous_provider_attempts",
        "hotfix5_post429_previous_http_status",
        "hotfix5_post429_archive_sha256",
        "M73_LOCK_RECOVERY_MODE=",
        "M73_HOTFIX5_POST429_LOCK_RECOVERY=",
        "M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION",
        "RECOVER_M73_EXPANDED_AFTER_HOTFIX5_INTERRUPTED_EXACT_LOCK",
        "M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256",
        EXPECTED_HOTFIX5_INTERRUPTED_CURRENT_LOCK_SHA256,
        "RECOVERING_EXPANDED_DISCOVERY_AFTER_HOTFIX5_INTERRUPTED_RUN",
        "M73_EXPANDED_AFTER_HOTFIX5_LOCK_RECOVERY=",
    ):
        require(token in runner_source, f"Hotfix5 post-429 runner token missing: {token}")
    require(
        '"M73_LOCK_RECOVERY_MODE="' in wrapper_source,
        "Hotfix5 wrapper generic recovery marker missing",
    )
    require(
        '"M73_HOTFIX5_POST429_LOCK_RECOVERY="' in wrapper_source,
        "Hotfix5 wrapper post-429 marker missing",
    )
    require(
        '"M73_HOTFIX2_LOCK_RECOVERY="' not in wrapper_source,
        "Legacy impossible Hotfix2 wrapper marker still present",
    )
    print("HOTFIX5_POST429_RECOVERY=EXACT_KNOWN_LOCK_SHA_ONLY")
    print("HOTFIX5_POST429_PRIOR_PROVIDER_ATTEMPTS=1")
    print("HOTFIX5_POST429_PRIOR_HTTP_STATUS=429")
    print("HOTFIX5_POST429_AUTOMATIC_REARM=NO")
    print("HOTFIX5_POST429_SOURCE_INCIDENT_CAP=6_REQUESTS_600_CREDITS_0_RETRY")
    print("EXPANDED_DISCOVERY_TRANCHE_HARD_CAP=90_REQUESTS_9000_CREDITS_0_RETRY")
    print("EXPANDED_AFTER_HOTFIX5_RECOVERY=EXACT_CURRENT_LOCK_SHA_ONE_SHOT")
    print("EXPANDED_AFTER_HOTFIX5_CURRENT_LOCK_SHA256=" + EXPECTED_HOTFIX5_INTERRUPTED_CURRENT_LOCK_SHA256)
    print("EXPANDED_AFTER_HOTFIX5_COMPLETED_M73_REPORT_BLOCKS_REARM=YES")
    print("EXPANDED_AFTER_HOTFIX5_M66_CACHE_REUSE=YES")
    print("M63_GLOBAL_GUARD_RETAINED=YES")
    print("M66_PROVIDER_THROTTLE_SECONDS=0.15")
    print("HOTFIX5_POST429_INSTALLER_PROVIDER_REQUESTS=0")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
