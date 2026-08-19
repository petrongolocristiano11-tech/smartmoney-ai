from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_controlled_new_wallet_qualification_service import (  # noqa: E402
    M66_HELIUS_CONFIRMATION,
    M73ControlledQualificationError,
    M73_RUN_CONFIRMATION,
    build_m73_report,
    choose_seed_wallet,
    classify_deep_candidate,
    extract_m66_candidates,
    known_m72_wallets,
    validate_m72_authorization,
    validate_m73_report,
    validate_runtime_limits,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    file_sha256,
    write_json_atomic,
)
from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67_service  # noqa: E402
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    M67_M70_DEFAULT_POLICY,
    validate_policy as validate_m67_policy,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import (  # noqa: E402
    CachedBudgetedPublicRpc,
    PublicRpcBudgetExhausted,
    _collect_deep_history,
    _finalize_cache,
    _load_cache,
    _signature_page,
)


EXPECTED_M66_WRAPPER_SHA256 = "665e267616bf50ef45864490d26f0cf4d5c8a37db1490000bba63a78f9a0ea81"
EXPECTED_M66_SERVICE_SHA256 = "f4312154f95a9256c5a02e62dd4a100414d28c9ed3812159c9b3a75f23e5581a"
EXPECTED_M66_RUNNER_SHA256 = "21da3da6d63c49d4c1443091552f44fbbc302579f19db3a2973c639673096ec4"
_M66_CONTROLLED_MARKER = re.compile(r"M66[_A-Z0-9]*CONTROLLED[_A-Z0-9]*=PASS")
_KV_MARKER = re.compile(r"^([A-Z0-9_]+)=(.*)$")

M73_HOTFIX2_RECOVERY_CONFIRMATION = (
    "RECOVER_M73_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2"
)
# This recovery is intentionally scoped to the exact M72 acquisition plan from
# the observed 2026-08-15 pre-network failure. It is NOT a generic re-arm.
M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256 = (
    "328abe2296e8b91700756376175337d24cffd598c3cf12e9bb49872c69405bd8"
)
M73_HOTFIX4_RECOVERY_CONFIRMATION = (
    "RECOVER_M73_PRENETWORK_CREDIT_GUARD_NOT_ENFORCED_HOTFIX3"
)
M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION = (
    "RECOVER_M73_POST_PROVIDER_HTTP_429_HOTFIX4_EXACT_LOCK"
)
M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256 = (
    "da93df4010d4f5e1fc8e11a323a1a9d573457f1e467712273620b660ed0642e0"
)
M73_HOTFIX5_KNOWN_PRIOR_PROVIDER_ATTEMPTS = 1
M73_HOTFIX5_KNOWN_PRIOR_HTTP_STATUS = 429

M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION = (
    "RECOVER_M73_EXPANDED_AFTER_HOTFIX5_INTERRUPTED_EXACT_LOCK"
)
M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256 = (
    "2897afff36d318876ed625e1924180c94bec1092fe7e5d39984f1646c9cc9342"
)
M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_STARTED_AT_UTC = (
    "2026-08-16T14:18:16.044425+00:00"
)

M73_POST_M66_EXPANDED_POLICY_FAILURE_RECOVERY_CONFIRMATION = (
    "RESUME_M73_AFTER_M66_EXPANDED_POLICY_FAILURE_EXACT_ARTIFACTS"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256 = (
    "1f6d6d3c73e3fcbc32f99482aa4b70fe0be6f3f89144c06a476e4dcef61ad99c"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_NAME = (
    "smartmoney-m66-controlled-helius-discovery-20260816T155111Z.json"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_SHA256 = (
    "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_NAME = (
    "smartmoney-m66-helius-request-cache-20260816T155111Z.json"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_SHA256 = (
    "0cab70ecee5d437bff83729337be2db547ff2f2680cb069d98540c78b9211c31"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_NAME = (
    "smartmoney-m66-m73-expanded-discovery-tranche-20260816T154757Z.txt"
)
M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_SHA256 = (
    "e58a5cf61785d30c89334c81fc1ab0f1279577837fbc7bd6a7204e6eda66568f"
)
_M73_LOCK_SCOPE = "M73_ONE_SHOT_EXECUTION_LOCK_FAIL_CLOSED"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M73: autorizza una singola tranche M66 expanded manual-only fino a 90/9000, "
            "poi usa solo RPC pubblico + cache SHA-256 per il gate economico Gen4."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--recovery-confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--m72-report", required=True)
    parser.add_argument("--m72-plan", required=True)
    parser.add_argument("--cache-input", required=True)
    parser.add_argument("--seed-wallet", default="")
    parser.add_argument("--rpc-url", default="https://api.mainnet-beta.solana.com")
    parser.add_argument("--public-rpc-request-cap", type=int, default=4000)
    parser.add_argument("--maximum-candidates", type=int, default=6)
    parser.add_argument("--maximum-signatures-per-candidate", type=int, default=500)
    return parser


def _load_json(path_text: str, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise M73ControlledQualificationError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M73ControlledQualificationError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M73ControlledQualificationError(f"Root {label} non oggetto.")
    return path, value


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _verify_m66_lane() -> Path:
    files = (
        (PROJECT_ROOT / "RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1", EXPECTED_M66_WRAPPER_SHA256),
        (
            PROJECT_ROOT / "backend/app/services/gen4_controlled_helius_discovery_service.py",
            EXPECTED_M66_SERVICE_SHA256,
        ),
        (PROJECT_ROOT / "scripts/run_m66_controlled_helius_discovery.py", EXPECTED_M66_RUNNER_SHA256),
    )
    for path, expected in files:
        if not path.is_file() or _sha256(path) != expected:
            raise M73ControlledQualificationError(
                f"Corsia M66 controllata non coincide con la baseline verificata: {path.name}."
            )
    return files[0][0]


def _powershell_executable() -> str:
    for name in ("powershell.exe", "pwsh.exe", "pwsh"):
        try:
            completed = subprocess.run(
                [name, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if completed.returncode == 0:
            return name
    raise M73ControlledQualificationError("PowerShell non disponibile per la corsia M66.")


def _preflight_m66_parameters(wrapper: Path) -> dict[str, str]:
    ps = _powershell_executable()
    env = dict(os.environ)
    env["SMARTMONEY_M73_M66_WRAPPER"] = str(wrapper)
    command = r'''
$ErrorActionPreference = "Stop"
$cmd = Get-Command -Name $env:SMARTMONEY_M73_M66_WRAPPER -ErrorAction Stop
$cmd.Parameters.Keys | Sort-Object | ForEach-Object { Write-Output $_ }
'''
    completed = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise M73ControlledQualificationError(
            "Preflight locale parametri wrapper M66 fallito; nessuna richiesta Helius eseguita."
        )
    names = {
        line.strip().lower(): line.strip()
        for line in (completed.stdout or "").splitlines()
        if line.strip()
    }
    aliases = {
        "project": ("ProjectRoot",),
        "output": ("OutputDirectory", "OutputDir"),
        "seed": ("SeedWallet", "SeedWalletAddress", "Seed"),
        "confirmation": ("Confirmation", "HeliusConfirmation", "Confirm"),
    }
    resolved: dict[str, str] = {}
    for role, candidates in aliases.items():
        for candidate in candidates:
            actual = names.get(candidate.lower())
            if actual:
                resolved[role] = actual
                break
        if role not in resolved:
            raise M73ControlledQualificationError(
                f"Wrapper M66 non espone il parametro {role} atteso; fail-closed prima di Helius."
            )
    return resolved


def _validate_database_public_url(value: str) -> None:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme.lower() not in {"postgres", "postgresql"} or not parsed.hostname:
        raise M73ControlledQualificationError(
            "DATABASE_PUBLIC_URL non valida; fail-closed prima del lock e prima di Helius."
        )
    if not parsed.username:
        raise M73ControlledQualificationError(
            "DATABASE_PUBLIC_URL priva di utente; fail-closed prima del lock e prima di Helius."
        )


def _preflight_database_public_url() -> str:
    value = str(os.environ.get("DATABASE_PUBLIC_URL") or "").strip()
    if not value:
        raise M73ControlledQualificationError(
            "DATABASE_PUBLIC_URL assente nel processo M73. Il wrapper deve avviare M73 "
            "tramite Railway Postgres prima del lock; nessun fallback a DATABASE_URL."
        )
    _validate_database_public_url(value)
    return "INHERITED_POSTGRES_ENVIRONMENT"


def _railway_executable() -> str:
    for name in ("railway.cmd", "railway.exe", "railway"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    raise M73ControlledQualificationError(
        "Railway CLI non disponibile per il preflight ambiente M66; "
        "fail-closed prima del lock e prima di Helius."
    )


def _valid_helius_api_key(value: object) -> bool:
    key = str(value or "").strip()
    return 20 <= len(key) <= 512 and not any(char.isspace() for char in key)


def _read_dotenv_value(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="strict").splitlines()
    except (OSError, UnicodeError):
        return ""
    selected = ""
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        selected = value.strip()
    return selected


def _railway_backend_helius_key() -> str:
    """Read an unsealed backend key into memory without printing it.

    HELIUS_API_KEY is deliberately removed from the parent environment before
    `railway run`, so an inherited local value cannot be mistaken for a value
    actually exported by the Railway backend service. Sealed Railway variables
    are intentionally CLI-invisible and therefore return an empty value here.
    """
    railway = _railway_executable()
    probe = (
        "import base64,os;"
        "value=str(os.getenv('HELIUS_API_KEY') or '').strip();"
        "print('M73_SECRET_CAPTURE_B64=' + base64.b64encode(value.encode()).decode())"
    )
    env = dict(os.environ)
    env.pop("HELIUS_API_KEY", None)
    completed = subprocess.run(
        [
            railway,
            "run",
            "--service",
            "smartmoney-ai",
            "--environment",
            "production",
            "--no-local",
            sys.executable,
            "-c",
            probe,
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    marker = "M73_SECRET_CAPTURE_B64="
    encoded = ""
    for raw in (completed.stdout or "").splitlines():
        line = raw.strip()
        if line.startswith(marker):
            encoded = line[len(marker):].strip()
    if not encoded:
        return ""
    try:
        import base64

        value = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        return ""
    return value.strip()


def _resolve_helius_api_key() -> tuple[str, str, dict[str, str]]:
    """Resolve Helius before the lock without performing a Helius API call."""
    railway_key = _railway_backend_helius_key()
    dotenv_key = _read_dotenv_value(PROJECT_ROOT / ".env", "HELIUS_API_KEY")
    inherited_key = str(os.environ.get("HELIUS_API_KEY") or "").strip()

    railway_ok = _valid_helius_api_key(railway_key)
    dotenv_ok = _valid_helius_api_key(dotenv_key)
    inherited_ok = _valid_helius_api_key(inherited_key)

    if railway_ok:
        chosen = railway_key
        source = "RAILWAY_BACKEND_UNSEALED"
    elif dotenv_ok:
        chosen = dotenv_key
        source = "LOCAL_DOTENV"
    elif inherited_ok:
        chosen = inherited_key
        source = "INHERITED_PROCESS_ENVIRONMENT"
    else:
        raise M73ControlledQualificationError(
            "HELIUS_API_KEY non risolvibile prima del lock: Railway backend non la esporta "
            "alla CLI e .env/processo locale non contengono una chiave formalmente valida. "
            "Nessuna richiesta Helius eseguita e lock non toccato."
        )

    evidence = {
        "railway_backend_exported": "YES_REDACTED" if railway_ok else "NO_OR_SEALED",
        "local_dotenv_present": "YES_REDACTED" if dotenv_ok else "NO",
        "inherited_process_present": "YES_REDACTED" if inherited_ok else "NO",
        "railway_matches_local_dotenv": (
            "YES" if railway_ok and dotenv_ok and railway_key == dotenv_key
            else "NO" if railway_ok and dotenv_ok
            else "NOT_COMPARABLE"
        ),
    }
    return chosen, source, evidence


def _sanitize_sensitive_output(value: str, *, helius_api_key: str = "") -> str:
    text = str(value or "")
    secret = str(helius_api_key or "").strip()
    if secret:
        text = text.replace(secret, "<REDACTED_HELIUS_API_KEY>")
    text = re.sub(
        r"(?i)(api-key=)[A-Za-z0-9._-]+",
        r"\1<REDACTED>",
        text,
    )
    text = re.sub(
        r"(?i)(HELIUS_API_KEY\s*[=:]\s*)[^\s]+",
        r"\1<REDACTED>",
        text,
    )
    text = re.sub(
        r"(?i)(postgres(?:ql)?(?:\+psycopg)?://[^:\s/@]+:)[^@\s]+(@)",
        r"\1<REDACTED>\2",
        text,
    )
    return text


def _load_execution_lock(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M73ControlledQualificationError(
            "Lock M73 presente ma non leggibile; fail-closed senza re-arm."
        ) from error
    if not isinstance(value, dict):
        raise M73ControlledQualificationError(
            "Lock M73 presente ma con root non oggetto; fail-closed senza re-arm."
        )
    return value


def _parse_aware_iso(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise M73ControlledQualificationError(
            "Timestamp lock M73 non valido; fail-closed senza re-arm."
        ) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _post_lock_network_artifacts(output_dir: Path, *, started: datetime) -> list[str]:
    patterns = (
        "*m66*controlled*.json",
        "*m66*helius*.json",
        "smartmoney-m73-controlled-new-wallet-qualification-*.json",
        "smartmoney-m73-public-rpc-cache-*.json",
    )
    cutoff_ns = int(started.timestamp() * 1_000_000_000)
    found: set[str] = set()
    for pattern in patterns:
        for path in output_dir.glob(pattern):
            try:
                if path.stat().st_mtime_ns >= cutoff_ns:
                    found.add(path.name)
            except OSError:
                continue
    return sorted(found)


def _load_exact_post_m66_resume_artifacts(output_dir: Path) -> dict[str, Any]:
    report_path = output_dir / M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_NAME
    cache_path = output_dir / M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_NAME
    log_path = output_dir / M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_NAME

    expected = (
        (report_path, M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_SHA256, "report M66"),
        (cache_path, M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_SHA256, "cache M66"),
        (log_path, M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_SHA256, "log M66/M73"),
    )
    for path, digest, label in expected:
        if not path.is_file():
            raise M73ControlledQualificationError(
                f"Resume post-M66 bloccata: {label} esatto non trovato ({path.name})."
            )
        if _sha256(path) != digest:
            raise M73ControlledQualificationError(
                f"Resume post-M66 bloccata: SHA {label} inatteso ({path.name})."
            )

    _, report = _load_json(str(report_path), label="Report M66 resume")
    budget = dict(report.get("budget") or {})
    pool = dict(report.get("candidate_pool") or {})
    summary = dict(report.get("summary") or {})
    activation = dict(report.get("activation") or {})

    exact_checks = {
        "scope": report.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "discovery": report.get("discovery") == "PASS",
        "budget_profile": report.get("budget_profile") == "EXPANDED_MANUAL_TRANCHE_9000",
        "seed_wallet": report.get("seed_wallet")
        == "F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        "enhanced_requests_executed": int(budget.get("enhanced_requests_executed") or -1) == 77,
        "enhanced_credits_reserved_maximum":
            int(budget.get("enhanced_credits_reserved_maximum") or -1) == 7700,
        "enhanced_request_cap": int(budget.get("enhanced_request_cap") or -1) == 86,
        "enhanced_credit_cap": int(budget.get("enhanced_credit_cap") or -1) == 8600,
        "maximum_retries": budget.get("maximum_retries") == 0,
        "cache_hits": int(budget.get("cache_hits") or -1) == 6,
        "new_wallets_found_before_limit":
            int(pool.get("new_wallets_found_before_limit") or -1) == 374,
        "wallets_prescreened": int(pool.get("wallets_prescreened") or -1) == 70,
        "prescreen_pass_needing_full_gen4_history":
            int(summary.get("prescreen_pass_needing_full_gen4_history") or -1) == 27,
        "micro_live_execution_authorized":
            activation.get("micro_live_execution_authorized") is False,
        "signer_authorized": activation.get("signer_authorized") is False,
    }
    failed = [name for name, ok in exact_checks.items() if not ok]
    if failed:
        raise M73ControlledQualificationError(
            "Resume post-M66 bloccata: contenuto report M66 inatteso: "
            + ", ".join(failed)
        )

    return {
        "report_path": report_path,
        "cache_path": cache_path,
        "log_path": log_path,
        "report": report,
    }


def _extract_ranked_m66_prescreen_pass_candidates(
    report: dict[str, Any],
    *,
    excluded_wallets: set[str],
    maximum_candidates: int = 80,
) -> list[dict[str, Any]]:
    raw_results = [
        dict(item)
        for item in report.get("candidate_results") or []
        if isinstance(item, dict)
    ]
    pass_rows: list[dict[str, Any]] = []
    for item in raw_results:
        if item.get("status") != "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST":
            continue
        normalized = dict(item)
        normalized["score"] = float(item.get("prescreen_score") or 0.0)
        pass_rows.append(normalized)

    expected_passes = int(
        dict(report.get("summary") or {}).get(
            "prescreen_pass_needing_full_gen4_history"
        )
        or 0
    )
    if expected_passes <= 0 or len(pass_rows) != expected_passes:
        raise M73ControlledQualificationError(
            "Report M66 resume incoerente: numero PRESCREEN_PASS inatteso."
        )

    rows = extract_m66_candidates(
        [("M66_EXACT_PRESCREEN_PASS_ONLY", {"candidate_results": pass_rows})],
        excluded_wallets=excluded_wallets,
        maximum_candidates=maximum_candidates,
    )
    if len(rows) != expected_passes:
        raise M73ControlledQualificationError(
            "Estrazione candidati M66 resume incompleta o contaminata."
        )
    return rows


def _m66_accounting_from_exact_report(report: dict[str, Any]) -> dict[str, Any]:
    budget = dict(report.get("budget") or {})
    return {
        "requests_reported": int(budget["enhanced_requests_executed"]),
        "credits_reported": int(budget["enhanced_credits_reserved_maximum"]),
        "request_cap": 90,
        "credit_cap": 9_000,
        "retries": 0,
        "accounting_marker_status": "REUSED_EXACT_M66_REPORT_NO_NEW_HELIUS",
        "new_helius_requests": 0,
        "new_helius_credits": 0,
    }


def _prepare_execution_lock(
    execution_lock: Path,
    *,
    output_dir: Path,
    m72_plan_file_sha256: str,
    recovery_confirmation: str,
    started: datetime,
) -> tuple[datetime, dict[str, Any]]:
    if not execution_lock.exists():
        payload = {
            "scope": _M73_LOCK_SCOPE,
            "state": "STARTED",
            "started_at_utc": started.isoformat(),
            "m72_plan_file_sha256": m72_plan_file_sha256,
            "helius_maximum_requests": 90,
            "helius_credit_cap": 9_000,
            "helius_retries": 0,
            "discovery_budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
            "automatic_rearm": False,
            "recovery_used": False,
            "hotfix4_recovery_used": False,
        }
        write_json_atomic(execution_lock, payload)
        return started, payload

    lock = _load_execution_lock(execution_lock)
    recovery_value = str(recovery_confirmation or "").strip()

    if recovery_value == M73_POST_M66_EXPANDED_POLICY_FAILURE_RECOVERY_CONFIRMATION:
        lock_sha256 = _sha256(execution_lock)
        if lock_sha256 != M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Resume post-M66 bloccata: SHA lock corrente inatteso; "
                "nessun re-run M66 consentito."
            )
        if m72_plan_file_sha256 != M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256:
            raise M73ControlledQualificationError(
                "Resume post-M66 bloccata: piano M72 diverso dal piano noto."
            )
        expected_current = {
            "scope": _M73_LOCK_SCOPE,
            "state": "RECOVERING_EXPANDED_DISCOVERY_AFTER_HOTFIX5_INTERRUPTED_RUN",
            "m72_plan_file_sha256": M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            "helius_maximum_requests": 90,
            "helius_credit_cap": 9_000,
            "helius_retries": 0,
            "automatic_rearm": False,
            "expanded_after_hotfix5_recovery_used": True,
            "expanded_after_hotfix5_source_lock_sha256":
                M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256,
            "expanded_after_hotfix5_recovery_started_at_utc":
                "2026-08-16T15:48:09.267372+00:00",
        }
        for key, expected_value in expected_current.items():
            if lock.get(key) != expected_value:
                raise M73ControlledQualificationError(
                    f"Resume post-M66 bloccata: campo lock inatteso ({key})."
                )
        if bool(lock.get("post_m66_expanded_policy_failure_recovery_used")):
            raise M73ControlledQualificationError(
                "Resume post-M66 già usata; nessun secondo resume consentito."
            )

        artifacts = _load_exact_post_m66_resume_artifacts(output_dir)
        expanded_started = _parse_aware_iso(
            lock.get("expanded_after_hotfix5_recovery_started_at_utc")
        )
        post_expanded_artifacts = _post_lock_network_artifacts(
            output_dir, started=expanded_started
        )
        completed_reports = [
            name for name in post_expanded_artifacts
            if name.startswith("smartmoney-m73-controlled-new-wallet-qualification-")
        ]
        if completed_reports:
            raise M73ControlledQualificationError(
                "Resume post-M66 vietata: esiste già un report M73 completato: "
                + ", ".join(completed_reports[:4])
            )

        archive_path = output_dir / (
            "smartmoney-m73-post-m66-expanded-policy-failure-lock-"
            + M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256[:16]
            + ".json"
        )
        original_bytes = execution_lock.read_bytes()
        if archive_path.exists():
            if _sha256(archive_path) != M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256:
                raise M73ControlledQualificationError(
                    "Archivio lock post-M66 già presente con SHA inatteso."
                )
        else:
            _write_bytes_atomic(archive_path, original_bytes)
        if _sha256(archive_path) != M73_POST_M66_EXPANDED_POLICY_FAILURE_KNOWN_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Archivio lock post-M66 non preserva lo SHA originale."
            )

        recovery_payload = {
            **lock,
            "state": "RECOVERING_M73_FROM_EXACT_M66_ARTIFACTS_AFTER_EXPANDED_POLICY_FAILURE",
            "post_m66_expanded_policy_failure_recovery_used": True,
            "post_m66_expanded_policy_failure_recovery_started_at_utc": started.isoformat(),
            "post_m66_expanded_policy_failure_recovery_reason":
                "M66_PASS_77_REQUESTS_7700_CREDITS_THEN_M67_RESOURCE_POLICY_REVALIDATION_FAILED",
            "post_m66_expanded_policy_failure_source_lock_sha256": lock_sha256,
            "post_m66_expanded_policy_failure_archive_file": str(archive_path),
            "post_m66_expanded_policy_failure_archive_sha256": _sha256(archive_path),
            "post_m66_resume_report_file": str(artifacts["report_path"]),
            "post_m66_resume_report_sha256":
                M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_SHA256,
            "post_m66_resume_cache_file": str(artifacts["cache_path"]),
            "post_m66_resume_cache_sha256":
                M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_SHA256,
            "post_m66_resume_log_file": str(artifacts["log_path"]),
            "post_m66_resume_log_sha256":
                M73_POST_M66_EXPANDED_POLICY_FAILURE_LOG_SHA256,
            "post_m66_expanded_policy_failure_recovery_contract":
                "EXACT_LOCK_EXACT_M66_REPORT_CACHE_LOG_SKIP_M66_ZERO_NEW_HELIUS_ONE_SHOT",
            "new_helius_requests_authorized": 0,
            "new_helius_credits_authorized": 0,
        }
        write_json_atomic(execution_lock, recovery_payload)
        return started, recovery_payload

    if recovery_value == M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION:
        lock_sha256 = _sha256(execution_lock)
        if lock_sha256 != M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Recovery expanded bloccata: SHA del lock corrente non coincide "
                "con lo stato Hotfix5 interrotto verificato; fail-closed senza Helius."
            )
        if m72_plan_file_sha256 != M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256:
            raise M73ControlledQualificationError(
                "Recovery expanded bloccata: piano M72 diverso dal piano noto."
            )
        expected_current = {
            "scope": _M73_LOCK_SCOPE,
            "state": "RECOVERING_POST_PROVIDER_HTTP_429_HOTFIX4",
            "m72_plan_file_sha256": M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            "helius_maximum_requests": 6,
            "helius_credit_cap": 600,
            "helius_retries": 0,
            "automatic_rearm": False,
            "recovery_used": True,
            "recovery_reason": "DATABASE_PUBLIC_URL_MISSING_BEFORE_M66_NETWORK_PREFLIGHT",
            "recovery_contract": "EXACT_PLAN_EXACT_STARTED_LOCK_NO_NEW_M66_M73_OUTPUTS",
            "hotfix4_recovery_used": True,
            "hotfix4_recovery_reason": "M63_CREDIT_GUARD_NOT_ENFORCED_BEFORE_FIRST_HELIUS_REQUEST",
            "hotfix4_recovery_contract": "EXACT_PLAN_EXACT_HOTFIX3_RECOVERY_LOCK_NO_NEW_M66_M73_OUTPUTS",
            "hotfix5_post429_recovery_used": True,
            "hotfix5_post429_recovery_reason": "M66_HELIUS_HTTP_429_AFTER_ONE_PROVIDER_ATTEMPT",
            "hotfix5_post429_previous_provider_attempts": 1,
            "hotfix5_post429_previous_http_status": 429,
            "hotfix5_post429_source_lock_sha256": M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256,
            "hotfix5_post429_archive_sha256": M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256,
            "hotfix5_post429_recovery_contract": "EXACT_LOCK_SHA_EXACT_PLAN_SINGLE_KNOWN_HTTP429_ONE_ATTEMPT_NO_M66_M73_OUTPUT",
            "hotfix5_post429_recovery_started_at_utc": M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_STARTED_AT_UTC,
        }
        for key, expected_value in expected_current.items():
            if lock.get(key) != expected_value:
                raise M73ControlledQualificationError(
                    f"Recovery expanded bloccata: campo lock corrente inatteso ({key})."
                )
        if bool(lock.get("expanded_after_hotfix5_recovery_used")):
            raise M73ControlledQualificationError(
                "Recovery expanded già usata; nessun secondo re-arm consentito."
            )

        hotfix5_started = _parse_aware_iso(
            lock.get("hotfix5_post429_recovery_started_at_utc")
        )
        post_hotfix5_artifacts = _post_lock_network_artifacts(
            output_dir, started=hotfix5_started
        )
        completed_reports = [
            name for name in post_hotfix5_artifacts
            if name.startswith("smartmoney-m73-controlled-new-wallet-qualification-")
        ]
        if completed_reports:
            raise M73ControlledQualificationError(
                "Recovery expanded vietata: esiste già un report M73 successivo a Hotfix5: "
                + ", ".join(completed_reports[:4])
            )
        reusable_m66_artifacts = [
            name for name in post_hotfix5_artifacts
            if "m66" in name.lower()
        ]

        archive_path = output_dir / (
            "smartmoney-m73-hotfix5-interrupted-lock-"
            + M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256[:16]
            + ".json"
        )
        original_bytes = execution_lock.read_bytes()
        if archive_path.exists():
            if _sha256(archive_path) != M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256:
                raise M73ControlledQualificationError(
                    "Archivio lock Hotfix5 interrotto già presente con SHA inatteso."
                )
        else:
            _write_bytes_atomic(archive_path, original_bytes)
        if _sha256(archive_path) != M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Archivio lock Hotfix5 interrotto non preserva lo SHA originale."
            )

        recovery_payload = {
            **lock,
            "state": "RECOVERING_EXPANDED_DISCOVERY_AFTER_HOTFIX5_INTERRUPTED_RUN",
            "expanded_after_hotfix5_recovery_used": True,
            "expanded_after_hotfix5_recovery_started_at_utc": started.isoformat(),
            "expanded_after_hotfix5_recovery_reason": (
                "HOTFIX5_LOCK_ADVANCED_BUT_RUNTIME_OUTPUT_DID_NOT_RETURN_TO_WRAPPER"
            ),
            "expanded_after_hotfix5_source_lock_sha256": lock_sha256,
            "expanded_after_hotfix5_archive_file": str(archive_path),
            "expanded_after_hotfix5_archive_sha256": _sha256(archive_path),
            "expanded_after_hotfix5_existing_m66_artifacts": reusable_m66_artifacts,
            "expanded_after_hotfix5_recovery_contract": (
                "EXACT_CURRENT_LOCK_SHA_EXACT_PLAN_NO_COMPLETED_M73_REPORT_"
                "PRESERVE_AND_REUSE_M66_CACHE_ONE_SHOT"
            ),
            "helius_maximum_requests": 90,
            "helius_credit_cap": 9_000,
            "helius_retries": 0,
            "discovery_budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
        }
        write_json_atomic(execution_lock, recovery_payload)
        return started, recovery_payload

    if recovery_value == M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION:
        lock_sha256 = _sha256(execution_lock)
        if lock_sha256 != M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Recovery Hotfix5 post-429 bloccata: SHA del lock M73 non coincide "
                "con il singolo incidente provider noto; fail-closed senza spesa Helius."
            )
        if m72_plan_file_sha256 != M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256:
            raise M73ControlledQualificationError(
                "Recovery Hotfix5 post-429 bloccata: piano M72 diverso dal piano noto."
            )
        expected_post429 = {
            "scope": _M73_LOCK_SCOPE,
            "state": "RECOVERING_PRENETWORK_CREDIT_GUARD_NOT_ENFORCED_HOTFIX3",
            "m72_plan_file_sha256": M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            "helius_maximum_requests": 6,
            "helius_credit_cap": 600,
            "helius_retries": 0,
            "automatic_rearm": False,
            "recovery_used": True,
            "recovery_reason": "DATABASE_PUBLIC_URL_MISSING_BEFORE_M66_NETWORK_PREFLIGHT",
            "recovery_contract": "EXACT_PLAN_EXACT_STARTED_LOCK_NO_NEW_M66_M73_OUTPUTS",
            "hotfix4_recovery_used": True,
            "hotfix4_recovery_reason": (
                "M63_CREDIT_GUARD_NOT_ENFORCED_BEFORE_FIRST_HELIUS_REQUEST"
            ),
            "hotfix4_recovery_contract": (
                "EXACT_PLAN_EXACT_HOTFIX3_RECOVERY_LOCK_NO_NEW_M66_M73_OUTPUTS"
            ),
        }
        for key, expected_value in expected_post429.items():
            if lock.get(key) != expected_value:
                raise M73ControlledQualificationError(
                    f"Recovery Hotfix5 post-429 bloccata: campo lock inatteso ({key})."
                )
        if bool(lock.get("hotfix5_post429_recovery_used")):
            raise M73ControlledQualificationError(
                "Recovery Hotfix5 post-429 già usata; nessun secondo re-arm consentito."
            )
        hotfix4_started = _parse_aware_iso(lock.get("hotfix4_recovery_started_at_utc"))
        artifacts = _post_lock_network_artifacts(output_dir, started=hotfix4_started)
        if artifacts:
            raise M73ControlledQualificationError(
                "Recovery Hotfix5 post-429 bloccata: esistono output M66/M73 successivi "
                "al tentativo noto: " + ", ".join(artifacts[:8])
            )
        archive_path = output_dir / (
            "smartmoney-m73-post429-incident-lock-"
            + M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256[:16]
            + ".json"
        )
        original_bytes = execution_lock.read_bytes()
        if archive_path.exists():
            if _sha256(archive_path) != M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256:
                raise M73ControlledQualificationError(
                    "Archivio incidente post-429 già presente con SHA inatteso; fail-closed."
                )
        else:
            _write_bytes_atomic(archive_path, original_bytes)
        if _sha256(archive_path) != M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256:
            raise M73ControlledQualificationError(
                "Archivio incidente post-429 non preserva lo SHA originale."
            )
        recovery_payload = {
            **lock,
            "state": "RECOVERING_POST_PROVIDER_HTTP_429_HOTFIX4",
            "hotfix5_post429_recovery_used": True,
            "hotfix5_post429_recovery_started_at_utc": started.isoformat(),
            "hotfix5_post429_recovery_reason": (
                "M66_HELIUS_HTTP_429_AFTER_ONE_PROVIDER_ATTEMPT"
            ),
            "hotfix5_post429_previous_provider_attempts": (
                M73_HOTFIX5_KNOWN_PRIOR_PROVIDER_ATTEMPTS
            ),
            "hotfix5_post429_previous_http_status": (
                M73_HOTFIX5_KNOWN_PRIOR_HTTP_STATUS
            ),
            "hotfix5_post429_source_lock_sha256": lock_sha256,
            "hotfix5_post429_archive_file": str(archive_path),
            "hotfix5_post429_archive_sha256": _sha256(archive_path),
            "hotfix5_post429_recovery_contract": (
                "EXACT_LOCK_SHA_EXACT_PLAN_SINGLE_KNOWN_HTTP429_ONE_ATTEMPT_"
                "NO_M66_M73_OUTPUT"
            ),
            "expanded_discovery_tranche_authorized": True,
            "expanded_discovery_tranche_maximum_requests": 90,
            "expanded_discovery_tranche_credit_cap": 9_000,
            "expanded_discovery_tranche_default_planned_requests": 86,
            "expanded_discovery_tranche_default_planned_credits": 8_600,
            "expanded_discovery_tranche_retries": 0,
        }
        write_json_atomic(execution_lock, recovery_payload)
        return started, recovery_payload

    if recovery_value != M73_HOTFIX4_RECOVERY_CONFIRMATION:
        raise M73ControlledQualificationError(
            "Lock M73 già presente. Nessun re-arm automatico. Per lo stato Hotfix5 "
            "interrotto verificato serve: "
            f"{M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION}."
        )
    expected = {
        "scope": _M73_LOCK_SCOPE,
        "state": "RECOVERING_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2",
        "m72_plan_file_sha256": M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        "helius_maximum_requests": 6,
        "helius_credit_cap": 600,
        "helius_retries": 0,
        "automatic_rearm": False,
        "recovery_used": True,
        "recovery_reason": "DATABASE_PUBLIC_URL_MISSING_BEFORE_M66_NETWORK_PREFLIGHT",
        "recovery_contract": "EXACT_PLAN_EXACT_STARTED_LOCK_NO_NEW_M66_M73_OUTPUTS",
    }
    for key, expected_value in expected.items():
        if lock.get(key) != expected_value:
            raise M73ControlledQualificationError(
                f"Lock M73 non coincide con il fallimento Hotfix3 noto ({key}); "
                "fail-closed senza seconda spesa Helius."
            )
    if m72_plan_file_sha256 != M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256:
        raise M73ControlledQualificationError(
            "Il piano M72 corrente non è quello del fallimento Hotfix3 noto; "
            "recovery Hotfix4 vietata."
        )
    # Hotfix3 reached M66 only after this timestamp and then failed before the
    # first provider request because the M63 guard was not enforced locally.
    hotfix3_started = _parse_aware_iso(lock.get("recovery_started_at_utc"))
    artifacts = _post_lock_network_artifacts(output_dir, started=hotfix3_started)
    if artifacts:
        raise M73ControlledQualificationError(
            "Recovery Hotfix4 bloccata: esistono output M66/M73 successivi al "
            "tentativo Hotfix3; zero-spend non è più dimostrabile dal contratto."
        )
    recovery_payload = {
        **lock,
        "state": "RECOVERING_PRENETWORK_CREDIT_GUARD_NOT_ENFORCED_HOTFIX3",
        "hotfix4_recovery_used": True,
        "hotfix4_recovery_started_at_utc": started.isoformat(),
        "hotfix4_recovery_reason": (
            "M63_CREDIT_GUARD_NOT_ENFORCED_BEFORE_FIRST_HELIUS_REQUEST"
        ),
        "hotfix4_recovery_contract": (
            "EXACT_PLAN_EXACT_HOTFIX3_RECOVERY_LOCK_NO_NEW_M66_M73_OUTPUTS"
        ),
    }
    write_json_atomic(execution_lock, recovery_payload)
    return started, recovery_payload


def _m66_runtime_env(helius_api_key: str) -> dict[str, str]:
    if not _valid_helius_api_key(helius_api_key):
        raise M73ControlledQualificationError(
            "HELIUS_API_KEY risolta non valida per ambiente M66."
        )
    env = dict(os.environ)
    env.update(
        {
            "HELIUS_API_KEY": helius_api_key,
            # M66 executes locally against the Railway database. M63 normally
            # enforces by ENVIRONMENT=production; here we explicitly enable the
            # same guard only for this controlled subprocess instead of lying
            # about the whole application environment.
            "HELIUS_CREDIT_GUARD_ENABLED": "true",
            "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION": "true",
            # Preserve M63 containment: this controlled lane is manual-only.
            "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED": "false",
        }
    )
    return env


def _preflight_m63_credit_guard(helius_api_key: str) -> dict[str, str]:
    """Prove the local M66 process will see M63 as enforced, with zero network."""
    env = _m66_runtime_env(helius_api_key)
    probe = r"""from backend.app.core.config import settings
from backend.app.services.helius_credit_guard_service import _guard_enforced
assert settings.HELIUS_CREDIT_GUARD_ENABLED is True
assert settings.HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION is True
assert settings.HELIUS_AUTOMATIC_ENHANCED_API_ENABLED is False
assert _guard_enforced() is True
print("M73_M63_LOCAL_CREDIT_GUARD=ENFORCED")
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    output = _sanitize_sensitive_output(
        (completed.stdout or "") + (completed.stderr or ""),
        helius_api_key=helius_api_key,
    )
    if completed.returncode != 0 or "M73_M63_LOCAL_CREDIT_GUARD=ENFORCED" not in output:
        raise M73ControlledQualificationError(
            "Preflight M63 credit guard locale fallito; fail-closed prima del lock "
            "e prima di Helius."
        )
    return {
        "guard_enabled": "YES",
        "enforce_in_non_production": "YES",
        "automatic_enhanced_api": "DISABLED",
        "network_requests": "0",
    }

def _invoke_m66_lane(
    wrapper: Path,
    *,
    output_dir: Path,
    seed_wallet: str,
    helius_api_key: str,
) -> str:
    ps = _powershell_executable()
    helper = r'''
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$wrapper = $env:SMARTMONEY_M73_M66_WRAPPER
$project = $env:SMARTMONEY_M73_PROJECT
$output = $env:SMARTMONEY_M73_OUTPUT
$seed = $env:SMARTMONEY_M73_SEED
$confirmation = $env:SMARTMONEY_M73_M66_CONFIRMATION
$command = Get-Command -Name $wrapper -ErrorAction Stop
$names = @($command.Parameters.Keys)
$bound = @{}
function Bind-One([string[]]$Aliases, [object]$Value, [bool]$Required) {
    foreach ($alias in $Aliases) {
        if ($names -contains $alias) {
            $script:bound[$alias] = $Value
            Write-Host "M73_M66_BOUND_$($alias.ToUpperInvariant())=YES"
            return
        }
    }
    if ($Required) {
        throw "Parametro M66 richiesto non riconosciuto: $($Aliases -join ',')"
    }
}
Bind-One @("ProjectRoot") $project $true
Bind-One @("OutputDirectory", "OutputDir") $output $true
Bind-One @("SeedWallet", "SeedWalletAddress", "Seed") $seed $true
Bind-One @("Confirmation", "HeliusConfirmation", "Confirm") $confirmation $true
Write-Host "M73_M66_PARAMETER_BINDING=PASS"
try {
    & $wrapper @bound
    if (-not $?) { throw "Corsia M66 ha restituito stato PowerShell false." }
}
catch {
    Write-Error $_
    exit 1
}
'''
    if not _valid_helius_api_key(helius_api_key):
        raise M73ControlledQualificationError(
            "HELIUS_API_KEY risolta non valida prima dell'invocazione M66."
        )
    env = _m66_runtime_env(helius_api_key)
    env.update(
        {
            "SMARTMONEY_M73_M66_WRAPPER": str(wrapper),
            "SMARTMONEY_M73_PROJECT": str(PROJECT_ROOT),
            "SMARTMONEY_M73_OUTPUT": str(output_dir),
            "SMARTMONEY_M73_SEED": seed_wallet,
            "SMARTMONEY_M73_M66_CONFIRMATION": M66_HELIUS_CONFIRMATION,
        }
    )
    completed = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", helper],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    raw_output = (completed.stdout or "") + (completed.stderr or "")
    output = _sanitize_sensitive_output(raw_output, helius_api_key=helius_api_key)
    print(output, end="" if output.endswith("\n") else "\n")
    if completed.returncode != 0:
        raise M73ControlledQualificationError(
            f"Corsia M66 controllata fallita con exit code {completed.returncode}."
        )
    if "M73_M66_PARAMETER_BINDING=PASS" not in output:
        raise M73ControlledQualificationError("Binding parametri M66 non verificato.")
    if "M66" not in output or "PASS" not in output or "CONTROLLED" not in output:
        raise M73ControlledQualificationError("Marker PASS della corsia M66 non osservato.")
    return output


def _marker_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in output.splitlines():
        match = _KV_MARKER.fullmatch(raw.strip())
        if match:
            values[match.group(1)] = match.group(2).strip()
    return values


def _accounting(output: str) -> dict[str, Any]:
    markers = _marker_values(output)
    requests = None
    credits = None
    for key, value in markers.items():
        upper = key.upper()
        if "HELIUS_REQUEST" in upper:
            try:
                requests = int(value)
            except ValueError:
                pass
        if "HELIUS_CREDIT" in upper and "CAP" not in upper:
            try:
                credits = int(value)
            except ValueError:
                pass
    if requests is not None and requests > 90:
        raise M73ControlledQualificationError("Accounting M66 supera 90 richieste Helius.")
    if credits is not None and credits > 9_000:
        raise M73ControlledQualificationError("Accounting M66 supera 9000 crediti Helius.")
    return {
        "requests_reported": requests,
        "credits_reported": credits,
        "request_cap": 90,
        "credit_cap": 9_000,
        "retries": 0,
        "accounting_marker_status": (
            "REPORTED" if requests is not None or credits is not None else "NOT_EXPOSED_BY_WRAPPER"
        ),
    }


def _candidate_json_paths(output_dir: Path, *, started_ns: int, stdout: str) -> list[Path]:
    candidates: set[Path] = set()
    for value in _marker_values(stdout).values():
        if value.lower().endswith(".json"):
            path = Path(value).expanduser()
            if path.is_file():
                candidates.add(path.resolve())
    for path in output_dir.glob("*.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        name = path.name.lower()
        if stat.st_mtime_ns >= started_ns and "m66" in name:
            candidates.add(path.resolve())
    if not candidates:
        for path in output_dir.glob("*m66*.json"):
            name = path.name.lower()
            if "helius" in name or "controlled" in name:
                candidates.add(path.resolve())
    return sorted(candidates)


def _load_documents(paths: list[Path]) -> list[tuple[str, Any]]:
    result: list[tuple[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        result.append((path.name, value))
    return result



def _resolve_exact_post_m66_resume_evidence(
    *,
    output_dir: Path,
    m72_report: dict[str, Any],
) -> tuple[dict[str, Any], list[Path], list[dict[str, Any]]]:
    excluded = known_m72_wallets(m72_report)
    artifacts = _load_exact_post_m66_resume_artifacts(output_dir)
    m66_report = dict(artifacts["report"])
    helius_accounting = _m66_accounting_from_exact_report(m66_report)
    m66_paths = [artifacts["report_path"], artifacts["cache_path"]]
    discovered = _extract_ranked_m66_prescreen_pass_candidates(
        m66_report,
        excluded_wallets=excluded,
        maximum_candidates=80,
    )
    return helius_accounting, m66_paths, discovered


def _build_m73_m67_model_policy(limits: dict[str, int]) -> dict[str, Any]:
    """Return an M67-valid Gen4 model policy while M73 owns resource limits.

    The M67 economic/parser helpers revalidate the policy internally. Therefore
    M73 must never pass its expanded resource envelope (6/4000 default, hard
    max 8/5000) through M67's legacy resource fields. M73 enforces its resource
    envelope separately via `limits`, candidate slicing, and the RPC budget.
    """
    deep_candidates = int(limits["deep_candidates"])
    public_rpc_requests = int(limits["public_rpc_requests"])
    signatures_per_candidate = int(limits["signatures_per_candidate"])

    if not 1 <= deep_candidates <= 8:
        raise M73ControlledQualificationError(
            "Numero candidati deep M73 fuori contratto expanded (1..8)."
        )
    if not 30 <= public_rpc_requests <= 5_000:
        raise M73ControlledQualificationError(
            "Cap RPC pubblico M73 fuori contratto expanded (30..5000)."
        )
    if not 100 <= signatures_per_candidate <= 500:
        raise M73ControlledQualificationError(
            "Firme per candidato M73 fuori contratto expanded (100..500)."
        )

    return validate_m67_policy(
        {
            **M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": min(deep_candidates, 3),
            "maximum_signatures_per_deep_wallet": signatures_per_candidate,
            "public_rpc_request_cap": min(public_rpc_requests, 2_000),
            "public_rpc_maximum_attempts": 4,
            "public_rpc_throttle_seconds": 0.75,
        }
    )


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M73_RUN_CONFIRMATION:
        raise M73ControlledQualificationError(
            f"Conferma richiesta: {M73_RUN_CONFIRMATION}."
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M73ControlledQualificationError("Output M73 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)
    limits = validate_runtime_limits(
        public_rpc_requests=args.public_rpc_request_cap,
        deep_candidates=args.maximum_candidates,
        signatures_per_candidate=args.maximum_signatures_per_candidate,
    )
    m72_report_path, m72_report = _load_json(args.m72_report, label="Report M72")
    m72_plan_path, m72_plan = _load_json(args.m72_plan, label="Piano M72")
    validate_m72_authorization(m72_report, m72_plan)
    cache_path = Path(args.cache_input).expanduser().resolve()
    if not cache_path.is_file():
        raise M73ControlledQualificationError("Cache RPC M71 obbligatoria non trovata.")
    seed = str(args.seed_wallet or "").strip() or choose_seed_wallet(m72_report)
    allowed_observe_seeds = {
        str(item.get("wallet_address"))
        for item in m72_report.get("wallet_rotation") or []
        if isinstance(item, dict) and item.get("disposition") == "OBSERVE_ONLY"
    }
    if seed not in allowed_observe_seeds:
        raise M73ControlledQualificationError(
            "Seed M73 deve appartenere esattamente ai candidati M72 OBSERVE_ONLY."
        )
    wrapper = _verify_m66_lane()
    m66_parameter_binding = _preflight_m66_parameters(wrapper)
    database_public_url_source = _preflight_database_public_url()
    helius_api_key, helius_api_key_source, helius_key_evidence = _resolve_helius_api_key()
    m63_guard_preflight = _preflight_m63_credit_guard(helius_api_key)

    parsed_url = urlsplit(str(args.rpc_url or ""))
    rpc_host = str(parsed_url.hostname or "").lower()
    if parsed_url.scheme.lower() != "https" or rpc_host != "api.mainnet-beta.solana.com":
        raise M73ControlledQualificationError(
            "M73 consente solo l'endpoint RPC pubblico Solana ufficiale, senza provider a crediti."
        )
    if parsed_url.query or parsed_url.username or parsed_url.password:
        raise M73ControlledQualificationError(
            "RPC M73 non puo contenere query/API key/credenziali."
        )
    public_origin = f"https://{rpc_host}"
    cache = _load_cache(str(cache_path), public_origin=public_origin)
    model_policy = _build_m73_m67_model_policy(limits)

    # Tutti i preflight locali devono essere PASS prima di creare il lock one-shot.
    # Dal lock in poi qualunque errore resta fail-closed e richiede revisione manuale,
    # evitando un secondo consumo Helius accidentale sullo stesso piano M72.
    m72_plan_file_sha256 = file_sha256(m72_plan_path)
    execution_lock = output_dir / (
        "smartmoney-m73-controlled-execution-lock-"
        + m72_plan_file_sha256[:16]
        + ".json"
    )
    started = datetime.now(timezone.utc)
    started, lock_state = _prepare_execution_lock(
        execution_lock,
        output_dir=output_dir,
        m72_plan_file_sha256=m72_plan_file_sha256,
        recovery_confirmation=str(args.recovery_confirmation or ""),
        started=started,
    )
    started_ns = int(started.timestamp() * 1_000_000_000)
    print("=== M73 CONTROLLED NEW WALLET ACQUISITION & QUALIFICATION ===")
    print(f"M73_SEED_WALLET={seed}")
    print("M73_HELIUS_MAXIMUM_REQUESTS=90")
    print("M73_HELIUS_CREDIT_CAP=9000")
    print("M73_HELIUS_RETRIES=0")
    print("M73_M66_LOCAL_PARAMETER_PREFLIGHT=PASS")
    print("M73_M66_PARAMETER_ROLES=" + ",".join(sorted(m66_parameter_binding)))
    print("M73_PUBLIC_RPC_PROVIDER=SOLANA_OFFICIAL_PUBLIC_ONLY")
    print("M73_DATABASE_PUBLIC_URL_PREFLIGHT=PASS")
    print(f"M73_DATABASE_PUBLIC_URL_SOURCE={database_public_url_source}")
    print("M73_M66_RUNTIME_ENV_PREFLIGHT=PASS")
    print("M73_M66_RUNTIME_DATABASE_PUBLIC_URL=YES")
    print("M73_M66_RUNTIME_HELIUS_API_KEY=YES_REDACTED")
    print(f"M73_HELIUS_API_KEY_SOURCE={helius_api_key_source}")
    print(
        "M73_RAILWAY_BACKEND_HELIUS_EXPORT="
        + helius_key_evidence["railway_backend_exported"]
    )
    print(
        "M73_LOCAL_DOTENV_HELIUS="
        + helius_key_evidence["local_dotenv_present"]
    )
    print(
        "M73_RAILWAY_LOCAL_HELIUS_MATCH="
        + helius_key_evidence["railway_matches_local_dotenv"]
    )
    print("M73_HELIUS_PREFLIGHT_NETWORK_REQUESTS=0")
    print("M73_M63_CREDIT_GUARD_PREFLIGHT=PASS")
    print("M73_M63_CREDIT_GUARD_ENABLED=" + m63_guard_preflight["guard_enabled"])
    print(
        "M73_M63_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION="
        + m63_guard_preflight["enforce_in_non_production"]
    )
    print("M73_M66_AUTOMATIC_ENHANCED_API=DISABLED")
    print("M73_M63_CREDIT_GUARD_PREFLIGHT_NETWORK_REQUESTS=0")
    if bool(lock_state.get("post_m66_expanded_policy_failure_recovery_used")):
        recovery_mode = "POST_M66_EXACT_ARTIFACT_RESUME_ZERO_NEW_HELIUS"
    elif bool(lock_state.get("expanded_after_hotfix5_recovery_used")):
        recovery_mode = "EXPANDED_EXACT_AFTER_HOTFIX5_INTERRUPTED_RUN"
    elif bool(lock_state.get("hotfix5_post429_recovery_used")):
        recovery_mode = "HOTFIX5_EXACT_POST_PROVIDER_HTTP_429"
    elif bool(lock_state.get("hotfix4_recovery_used")):
        recovery_mode = "HOTFIX4_EXACT_HOTFIX3_GUARD_PRENETWORK_FAILURE"
    else:
        recovery_mode = "NOT_REQUIRED"
    print("M73_LOCK_RECOVERY_MODE=" + recovery_mode)
    print(
        "M73_EXPANDED_AFTER_HOTFIX5_LOCK_RECOVERY="
        + (
            "AUTHORIZED_EXACT_CURRENT_LOCK"
            if bool(lock_state.get("expanded_after_hotfix5_recovery_used"))
            else "NOT_USED"
        )
    )
    print(
        "M73_HOTFIX5_POST429_LOCK_RECOVERY="
        + (
            "AUTHORIZED_EXACT_KNOWN_LOCK"
            if bool(lock_state.get("hotfix5_post429_recovery_used"))
            else "NOT_USED"
        )
    )
    print(
        "M73_POST_M66_EXACT_RESUME="
        + (
            "AUTHORIZED_SKIP_M66_ZERO_NEW_HELIUS"
            if bool(lock_state.get("post_m66_expanded_policy_failure_recovery_used"))
            else "NOT_USED"
        )
    )
    resume_post_m66 = bool(
        lock_state.get("post_m66_expanded_policy_failure_recovery_used")
    )
    excluded = known_m72_wallets(m72_report)
    if resume_post_m66:
        helius_accounting, m66_paths, discovered = _resolve_exact_post_m66_resume_evidence(
            output_dir=output_dir,
            m72_report=m72_report,
        )
        print("M73_M66_RESUME_MODE=EXACT_EXISTING_M66_ARTIFACTS_ZERO_NEW_HELIUS")
        print("M73_M66_INVOKED=NO")
        print("M73_NEW_HELIUS_REQUESTS=0")
        print("M73_NEW_HELIUS_CREDITS=0")
        print(
            "M73_REUSED_M66_REPORT_SHA256="
            + M73_POST_M66_EXPANDED_POLICY_FAILURE_REPORT_SHA256
        )
        print(
            "M73_REUSED_M66_CACHE_SHA256="
            + M73_POST_M66_EXPANDED_POLICY_FAILURE_CACHE_SHA256
        )
        print(f"M73_M66_PRESCREEN_PASS_CANDIDATES={len(discovered)}")
    else:
        m66_output = _invoke_m66_lane(
            wrapper,
            output_dir=output_dir,
            seed_wallet=seed,
            helius_api_key=helius_api_key,
        )
        helius_accounting = _accounting(m66_output)
        m66_paths = _candidate_json_paths(
            output_dir, started_ns=started_ns, stdout=m66_output
        )
        if not m66_paths:
            raise M73ControlledQualificationError(
                "Corsia M66 PASS ma nessun output JSON controllato e stato trovato; fail-closed."
            )
        documents = _load_documents(m66_paths)
        m66_reports = [
            document
            for _source, document in documents
            if isinstance(document, dict)
            and document.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY"
            and document.get("discovery") == "PASS"
        ]
        if m66_reports:
            newest_report = max(
                m66_reports,
                key=lambda item: str(item.get("executed_at_utc") or ""),
            )
            discovered = _extract_ranked_m66_prescreen_pass_candidates(
                newest_report,
                excluded_wallets=excluded,
                maximum_candidates=80,
            )
        else:
            discovered = extract_m66_candidates(
                documents,
                excluded_wallets=excluded,
                maximum_candidates=80,
            )

    selected = discovered[: limits["deep_candidates"]]
    print(
        "M73_SELECTED_DEEP_WALLETS="
        + ",".join(str(item["wallet_address"]) for item in selected)
    )

    rpc = CachedBudgetedPublicRpc(
        args.rpc_url,
        cache=cache,
        request_cap=limits["public_rpc_requests"],
        maximum_attempts=int(model_policy["public_rpc_maximum_attempts"]),
        throttle_seconds=float(model_policy["public_rpc_throttle_seconds"]),
    )
    evaluated: list[dict[str, Any]] = []
    try:
        for candidate in selected:
            wallet = str(candidate["wallet_address"])
            try:
                first_page = _signature_page(
                    rpc,
                    wallet,
                    limit=int(model_policy["signature_page_limit"]),
                )
                deep = _collect_deep_history(
                    rpc,
                    wallet,
                    first_page=first_page,
                    now=started,
                    policy=model_policy,
                )
            except PublicRpcBudgetExhausted:
                deep = {
                    "wallet_address": wallet,
                    "history_complete": False,
                    "public_rpc_budget_exhausted": True,
                    "signature_count": 0,
                    "transaction_count": 0,
                    "parsed_event_count": 0,
                    "backtest": {},
                }
            backtest = dict(deep.get("backtest") or {})
            economic = (
                m67_service._economic_analysis(backtest, model_policy)  # noqa: SLF001
                if backtest
                else None
            )
            evaluated.append(classify_deep_candidate(candidate, deep, economic))
    finally:
        rpc.close()

    cache = _finalize_cache(cache)
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    output_cache = output_dir / f"smartmoney-m73-public-rpc-cache-{timestamp}.json"
    write_json_atomic(output_cache, cache)
    m66_files = [
        {"file": str(path), "sha256": file_sha256(path)} for path in m66_paths
    ]
    cache_integrity = str(dict(cache.get("integrity") or {}).get("payload_sha256") or "")
    report = build_m73_report(
        m72_report_sha256=file_sha256(m72_report_path),
        m72_plan_sha256=file_sha256(m72_plan_path),
        seed_wallet=seed,
        m66_files=m66_files,
        discovered_candidates=discovered,
        evaluated_candidates=evaluated,
        helius_accounting=helius_accounting,
        public_rpc_stats=rpc.stats(),
        limits=limits,
        cache_payload_sha256=cache_integrity,
        evaluated_at=started,
    )
    validate_m73_report(report)
    report_path = output_dir / f"smartmoney-m73-controlled-new-wallet-qualification-{timestamp}.json"
    write_json_atomic(report_path, report)
    write_json_atomic(
        execution_lock,
        {
            **lock_state,
            "scope": _M73_LOCK_SCOPE,
            "state": "COMPLETED",
            "started_at_utc": str(lock_state.get("started_at_utc") or started.isoformat()),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "m72_plan_file_sha256": m72_plan_file_sha256,
            "helius_maximum_requests": 90,
            "helius_credit_cap": 9_000,
            "helius_retries": 0,
            "discovery_budget_profile": "EXPANDED_MANUAL_TRANCHE_9000",
            "automatic_rearm": False,
            "m73_report_file": str(report_path),
            "m73_report_sha256": file_sha256(report_path),
        },
    )
    summary = dict(report.get("summary") or {})
    stats = dict(report.get("public_rpc") or {})
    print("M73_CONTROLLED_ACQUISITION_AND_QUALIFICATION=PASS")
    print(f"M66_CONTROLLED_OUTPUT_FILES={len(m66_files)}")
    print(f"NEW_CANDIDATES_DISCOVERED={summary.get('candidates_discovered', 0)}")
    print(f"CANDIDATES_DEEP_ANALYZED={summary.get('candidates_deep_analyzed', 0)}")
    print(f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('qualified_pending_short_canary', 0)}")
    print(f"OBSERVE_ONLY={summary.get('observe_only', 0)}")
    print(f"RESEARCH_ONLY={summary.get('research_only', 0)}")
    print(f"REJECTED_FROM_PROMOTION={summary.get('rejected_from_promotion', 0)}")
    print(f"PUBLIC_RPC_REQUEST_CAP={limits['public_rpc_requests']}")
    print(f"PUBLIC_RPC_REQUESTS={int(stats.get('requests') or 0)}")
    print(f"PUBLIC_RPC_CACHE_HITS={int(stats.get('cache_hits') or 0)}")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("DATABASE_CANDIDATE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("SHORT_CANARY_EXECUTION_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print(f"M73_REPORT_FILE={report_path}")
    print(f"M73_REPORT_SHA256={file_sha256(report_path)}")
    print(f"M73_EXECUTION_LOCK_FILE={execution_lock}")
    print(f"M73_PUBLIC_RPC_CACHE_FILE={output_cache}")
    print(f"M73_PUBLIC_RPC_CACHE_SHA256={file_sha256(output_cache)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M73_CONTROLLED_ACQUISITION_AND_QUALIFICATION=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        raise SystemExit(1) from None
