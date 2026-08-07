from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT_PREFIX = "ea1c236"
PARENT_HEAD = "b6f8d2e4c731"
TARGET_HEAD = "c8a1f3d6e942"
BACKEND_SERVICE = "smartmoney-ai"
FRONTEND_SERVICE = "smartmoney-frontend"
POSTGRES_SERVICE = "Postgres"
ENVIRONMENT = "production"
BACKEND_URL = "https://smartmoney-ai-production-0042.up.railway.app"
FRONTEND_URL = "https://smartmoney-frontend-production-0e99.up.railway.app"
REMOTE_LOGICAL_DATABASE = "smartmoney_gen4"
DEPLOY_CONFIRMATION = "DEPLOY_AND_ACTIVATE_M61_PARALLEL_CANDIDATE"
EXPECTED_PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
EXPECTED_PRIMARY_ANCHOR = "2026-08-03T23:04:08.419988+00:00"
EXPECTED_PRIMARY_WALLETS = {
    "FsKYLBwxLQk5YMNSPYQcqceW6o8tJGF7U1aBHyEvGAyE",
    "2ZwYWRaQR7X3zcD7VX8u4Ke8znPQuKrVpRnU3Tp6UH7S",
}
EXPECTED_CANDIDATE_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"

PAYLOAD_FILES = [
    "backend/app/models/gen4_copyability.py",
    "backend/app/services/blockchain_parser_gen4_copyability_service.py",
    "backend/app/workers/gen4_copyability_worker.py",
    "backend/app/schemas/blockchain_integrity.py",
    "backend/app/main.py",
    "frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx",
    "frontend/src/services/gen4ForwardApi.js",
    "frontend/src/pages/Gen4Forward.jsx",
    "alembic/versions/c8a1f3d6e942_add_gen4_parallel_candidate_copyability.py",
    "scripts/activate_gen4_parallel_candidate_m61.py",
    "scripts/configure_gen4_copyability_helius_webhook.py",
    "scripts/deploy_gen4_parallel_candidate_m61.py",
    "scripts/rollback_gen4_parallel_candidate_m61.py",
    "scripts/test_gen4_parallel_candidate_postgresql_migration.py",
    "scripts/verify_gen4_parallel_candidate_m61.py",
    "tests/test_gen4_parallel_candidate_m61.py",
    "tests/test_gen4_parallel_candidate_frontend_m61.py",
    "README_GEN4_PARALLEL_CANDIDATE_M61.md",
    "TEST_RESULTS_GEN4_PARALLEL_CANDIDATE_M61.txt",
    "PATCH_FILES_GEN4_PARALLEL_CANDIDATE_M61.txt",
    "ROLLBACK_M61_SAFE.ps1",
]


class DeployError(RuntimeError):
    pass


def run(
    command: Iterable[object],
    *,
    cwd: Path,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    args = [str(item) for item in command]
    print("+ " + subprocess.list2cmdline(args))
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        check=False,
        capture_output=capture,
        env=env,
    )
    if capture and result.stdout:
        print(result.stdout, end="")
    if capture and result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if check and result.returncode != 0:
        raise DeployError(
            f"Comando fallito ({result.returncode}): "
            f"{subprocess.list2cmdline(args)}"
        )
    return result


def capture(command: Iterable[object], *, cwd: Path) -> str:
    return (run(command, cwd=cwd, capture=True).stdout or "").strip()


def resolve_executable(name: str) -> str:
    value = shutil.which(name) or shutil.which(name + ".exe")
    if not value:
        raise DeployError(f"Eseguibile non trovato: {name}")
    return value


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def required_secret(values: dict[str, str], name: str) -> str:
    value = str(values.get(name) or os.environ.get(name) or "").strip()
    if not value:
        raise DeployError(f"Segreto locale richiesto ma mancante: {name}")
    return value


def collect_head_assertion_files(repo: Path) -> list[str]:
    result: list[str] = []
    for path in sorted((repo / "tests").glob("test_*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        if "scripts.get_heads()" in source and TARGET_HEAD in source:
            result.append(path.relative_to(repo).as_posix())
    return result


def parse_porcelain_v1_z(output: str) -> set[str]:
    """Parse ``git status --porcelain=v1 -z`` without destroying XY spacing.

    The normal porcelain format starts tracked changes with a significant leading
    space (for example ``" M backend/app/main.py"``).  Calling ``strip()`` on
    the complete command output therefore corrupts the first path.  The ``-z``
    form is also safe for spaces and unusual characters in filenames.
    """

    records = output.split("\0")
    paths: set[str] = set()
    index = 0

    while index < len(records):
        record = records[index]
        if not record:
            index += 1
            continue
        if len(record) < 4 or record[2] != " ":
            raise DeployError(
                "Output git status --porcelain=v1 -z non valido: "
                + repr(record[:120])
            )

        xy = record[:2]
        relative = record[3:].replace("\\", "/")
        if not relative:
            raise DeployError("Percorso vuoto in git status porcelain.")
        paths.add(relative)

        # In porcelain v1 -z a rename/copy is emitted as:
        # ``XY <destination>\0<source>\0``.  The destination is the path that
        # must be validated against the M61 allow-list; consume the source entry.
        if "R" in xy or "C" in xy:
            index += 1
            if index >= len(records) or not records[index]:
                raise DeployError("Rename/copy git status incompleto.")

        index += 1

    return paths


def status_paths(repo: Path) -> set[str]:
    result = run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        cwd=repo,
        capture=True,
    )
    return parse_porcelain_v1_z(result.stdout or "")


def porcelain_parser_self_test() -> None:
    expected = {
        "backend/app/main.py",
        "backend/app/models/gen4_copyability.py",
        "README_GEN4_PARALLEL_CANDIDATE_M61.md",
        "tests/a file with spaces.py",
        "new/name.py",
    }
    sample = (
        " M backend/app/main.py\0"
        " M backend/app/models/gen4_copyability.py\0"
        "?? README_GEN4_PARALLEL_CANDIDATE_M61.md\0"
        "?? tests/a file with spaces.py\0"
        "R  new/name.py\0old/name.py\0"
    )
    actual = parse_porcelain_v1_z(sample)
    if actual != expected:
        raise DeployError(
            "Self-test parser porcelain fallito. "
            f"Expected={sorted(expected)} Actual={sorted(actual)}"
        )


def local_preflight_only(repo: Path) -> int:
    porcelain_parser_self_test()
    patched, commit_already_created = verify_local_install(repo)
    actual = status_paths(repo)
    print("M61_DEPLOY_PORCELAIN_SELF_TEST=PASS")
    print("M61_DEPLOY_LOCAL_PREFLIGHT=PASS")
    print(f"GIT_CHANGED_PATHS_VALIDATED={len(actual)}")
    print(f"HEAD_ASSERTION_FILES={len(patched)}")
    print(
        "M61_COMMIT_ALREADY_CREATED="
        + ("YES" if commit_already_created else "NO")
    )
    print("NETWORK_HELIUS=NO")
    print("NETWORK_JUPITER=NO")
    print("RAILWAY_CONNECTION=NO")
    print("RAILWAY_MODIFIED=NO")
    print("DATABASE_MODIFIED=NO")
    print("GIT_COMMIT=NO")
    print("GIT_PUSH=NO")
    return 0


def verify_local_install(repo: Path) -> tuple[list[str], bool]:
    if capture(["git", "branch", "--show-current"], cwd=repo) != "main":
        raise DeployError("Branch Git richiesta: main")
    head = capture(["git", "rev-parse", "HEAD"], cwd=repo)
    current = capture([sys.executable, "-m", "alembic", "current"], cwd=repo)
    heads = capture([sys.executable, "-m", "alembic", "heads"], cwd=repo)
    if TARGET_HEAD not in current or TARGET_HEAD not in heads:
        raise DeployError("M61 locale non installata/testata alla head c8a1f3d6e942.")
    if len([line for line in heads.splitlines() if "(head)" in line]) != 1:
        raise DeployError("Alembic non ha una sola head prima del deploy M61.")

    patched = collect_head_assertion_files(repo)
    actual = status_paths(repo)

    if head.startswith(BASELINE_COMMIT_PREFIX):
        allowed = set(PAYLOAD_FILES) | set(patched)
        missing = [relative for relative in PAYLOAD_FILES if relative not in actual]
        unexpected = sorted(actual - allowed)
        if missing:
            raise DeployError(
                "Installazione locale M61 incompleta; file non modificati/aggiunti: "
                + ", ".join(missing)
            )
        if unexpected:
            raise DeployError("Modifiche locali inattese: " + ", ".join(unexpected))
        run(["git", "diff", "--check"], cwd=repo)
        return patched, False

    subject = capture(["git", "log", "-1", "--pretty=%s"], cwd=repo)
    if subject != "feat: add Gen4 parallel candidate copyability M61":
        raise DeployError(
            "HEAD non è né la baseline ea1c236 né un commit M61 riconoscibile: " + head
        )
    if actual:
        raise DeployError(
            "Riesecuzione deploy M61 consentita solo con worktree pulita dopo il commit M61."
        )
    run(["git", "diff", "HEAD^", "HEAD", "--check"], cwd=repo)
    return patched, True


def railway_injected_values(
    repo: Path,
    service: str,
    names: list[str],
) -> dict[str, str | None]:
    railway = resolve_executable("railway")
    code = (
        "import json,os;"
        "print(json.dumps({k:os.getenv(k) for k in " + repr(names) + "}))"
    )
    result = run(
        [
            railway,
            "run",
            "--service",
            service,
            "--environment",
            ENVIRONMENT,
            "--no-local",
            sys.executable,
            "-c",
            code,
        ],
        cwd=repo,
        capture=True,
    )
    for line in reversed((result.stdout or "").splitlines()):
        try:
            parsed = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise DeployError(f"Impossibile leggere le variabili Railway per {service}.")


def replace_database(url: str, database: str) -> str:
    parts = urllib.parse.urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise DeployError("DATABASE_PUBLIC_URL Railway non valida.")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, f"/{database}", parts.query, parts.fragment)
    )


def sqlalchemy_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def remote_database_url(repo: Path) -> str:
    values = railway_injected_values(repo, POSTGRES_SERVICE, ["DATABASE_PUBLIC_URL"])
    public = str(values.get("DATABASE_PUBLIC_URL") or "").strip()
    if not public:
        raise DeployError("DATABASE_PUBLIC_URL Railway non disponibile.")
    return replace_database(public, REMOTE_LOGICAL_DATABASE)


def remote_alembic_head(database_url: str) -> str:
    engine = create_engine(sqlalchemy_url(database_url), future=True, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            value = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        return str(value or "")
    finally:
        engine.dispose()


def create_remote_db_dump(repo: Path, backup: Path, database_url: str) -> Path:
    docker = resolve_executable("docker")
    backup.mkdir(parents=True, exist_ok=True)
    destination = backup / "railway-smartmoney-gen4-pre-m61.dump"
    mount_source = str(backup.resolve()).replace("\\", "/")
    run(
        [
            docker,
            "run",
            "--rm",
            "-v",
            f"{mount_source}:/backup",
            "postgres:18",
            "pg_dump",
            "-Fc",
            "--no-owner",
            "--no-acl",
            f"--dbname={database_url}",
            "--file=/backup/railway-smartmoney-gen4-pre-m61.dump",
        ],
        cwd=repo,
    )
    if not destination.is_file() or destination.stat().st_size == 0:
        raise DeployError("Dump database logico Railway M61 non creato.")
    return destination


def wait_http(url: str, *, attempts: int = 96) -> None:
    last = ""
    for _ in range(attempts):
        try:
            response = httpx.get(url, timeout=8.0, follow_redirects=True)
            if 200 <= response.status_code < 300:
                return
            last = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last = type(exc).__name__
        time.sleep(5)
    raise DeployError(f"Endpoint non disponibile: {url}. Ultimo risultato: {last}")


def deploy_service(repo: Path, service: str, message: str) -> None:
    railway = resolve_executable("railway")
    run(
        [
            railway,
            "up",
            "--service",
            service,
            "--environment",
            ENVIRONMENT,
            "--yes",
            "--message",
            message,
        ],
        cwd=repo,
    )


def online_status(automation_key: str) -> dict[str, Any]:
    response = httpx.get(
        f"{BACKEND_URL}/integrity/parser-gen4-copyability/status",
        params={"recent_limit": 5},
        headers={"X-Automation-Key": automation_key, "Accept": "application/json"},
        timeout=30.0,
    )
    if response.is_error:
        raise DeployError(f"Status M61 online HTTP {response.status_code}.")
    data = response.json()
    if not isinstance(data, dict) or data.get("m61_parallel_candidate_support") is not True:
        raise DeployError("Status online non espone il supporto M61.")
    campaigns = [
        item for item in (data.get("active_campaigns") or []) if isinstance(item, dict)
    ]
    if int(data.get("active_campaign_count") or 0) != 2 or len(campaigns) != 2:
        raise DeployError("Attese esattamente due campagne copyability attive.")
    primary = next(
        (item for item in campaigns if item.get("campaign_role") == "PRIMARY_FORWARD"),
        None,
    )
    candidate = next(
        (item for item in campaigns if item.get("campaign_role") == "QUALIFIED_CANDIDATE"),
        None,
    )
    if primary is None or candidate is None:
        raise DeployError("Ruoli M61 online incompleti.")
    if str(primary.get("campaign_id")) != EXPECTED_PRIMARY_CAMPAIGN_ID:
        raise DeployError("Campaign ID primario cambiato.")
    if str(primary.get("anchor_at")) != EXPECTED_PRIMARY_ANCHOR:
        raise DeployError("Anchor primario cambiato.")
    if set(primary.get("frozen_wallets") or []) != EXPECTED_PRIMARY_WALLETS:
        raise DeployError("Wallet primari cambiati.")
    if set(candidate.get("frozen_wallets") or []) != {EXPECTED_CANDIDATE_WALLET}:
        raise DeployError("Wallet candidato online inatteso.")
    for campaign in (primary, candidate):
        if campaign.get("status") != "ACTIVE":
            raise DeployError("Una campagna M61 non è ACTIVE.")
        if (campaign.get("webhook") or {}).get("status") != "ACTIVE":
            raise DeployError("Webhook M61 non ACTIVE su entrambe le campagne.")
    required_zero = {
        "signer_access": False,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "paper_orders_created": 0,
        "live_orders_created": 0,
        "automatic_live_activation": False,
    }
    safety = data.get("safety") or {}
    for key, expected in required_zero.items():
        if safety.get(key) != expected:
            raise DeployError(f"Guardia sicurezza online non valida: {key}")
    return data


def write_report(
    backup: Path,
    *,
    commit: str,
    dump: Path,
    candidate_id: str,
    remote_head_before: str,
    remote_head_after: str,
) -> Path:
    report = backup / "M61_DEPLOY_ACTIVATION_REPORT.json"
    report.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "commit": commit,
                "parent_head": PARENT_HEAD,
                "target_head": TARGET_HEAD,
                "remote_head_before": remote_head_before,
                "remote_head_after": remote_head_after,
                "primary_campaign_id": EXPECTED_PRIMARY_CAMPAIGN_ID,
                "primary_anchor": EXPECTED_PRIMARY_ANCHOR,
                "primary_wallets": sorted(EXPECTED_PRIMARY_WALLETS),
                "candidate_campaign_id": candidate_id,
                "candidate_wallet": EXPECTED_CANDIDATE_WALLET,
                "active_campaign_count": 2,
                "webhook_wallet_count": 3,
                "remote_database_dump": str(dump),
                "no_signer": True,
                "no_signature": True,
                "no_submission": True,
                "paper_enabled": False,
                "live_enabled": False,
                "secrets_in_report": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    repo = PROJECT_ROOT
    backup = repo / ".smartmoney-backups" / (
        "gen4-parallel-candidate-m61-deploy-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    local_commit_created = False
    remote_deploy_started = False

    print("M61_DEPLOY_ACTIVATE=PRECHECK")
    print("PRIMARY_CAMPAIGN_MUTATION=FORBIDDEN")
    print("NEW_HELIUS_WEBHOOK=NO")
    print("HELIUS_WEBHOOK_UNION_WALLETS=3")
    print("PAPER=DISABLED")
    print("LIVE=DISABLED")
    print("SIGNER=ABSENT")

    try:
        patched, commit_already_created = verify_local_install(repo)
        dotenv = read_dotenv(repo / ".env")
        helius_key = required_secret(dotenv, "HELIUS_API_KEY")
        automation_key = required_secret(dotenv, "AUTOMATION_API_KEY")
        webhook_secret = required_secret(
            dotenv,
            "CANONICAL_PARSER_GEN4_COPYABILITY_WEBHOOK_SECRET",
        )
        if len(helius_key) < 20 or any(char.isspace() for char in helius_key):
            raise DeployError("HELIUS_API_KEY locale non sembra valida.")
        if len(automation_key) < 20:
            raise DeployError("AUTOMATION_API_KEY locale non sembra valida.")
        if len(webhook_secret) < 20:
            raise DeployError("Webhook secret locale non sembra valido.")
        print("SECRETS=LOADED_REDACTED")

        database_url = remote_database_url(repo)
        remote_before = remote_alembic_head(database_url)
        if remote_before not in {PARENT_HEAD, TARGET_HEAD}:
            raise DeployError(
                f"Head Railway inattesa prima di M61: {remote_before or 'NONE'}"
            )
        print(
            "REMOTE_M61_RESUME_MODE="
            + ("YES" if remote_before == TARGET_HEAD else "NO")
        )
        dump = create_remote_db_dump(repo, backup, database_url)
        print(f"RAILWAY_DB_BACKUP={dump}")
        print(f"REMOTE_ALEMBIC_BEFORE={remote_before}")

        confirmation = input(
            "Scrivi esattamente " + DEPLOY_CONFIRMATION + " per autorizzare "
            "commit, deploy Railway, migrazione M61 e aggiornamento del webhook esistente: "
        ).strip()
        if confirmation != DEPLOY_CONFIRMATION:
            raise DeployError("Conferma deploy M61 non fornita.")

        if commit_already_created:
            commit = capture(["git", "rev-parse", "HEAD"], cwd=repo)
            local_commit_created = True
            print("M61_COMMIT_REUSED=YES")
        else:
            stage_paths = list(dict.fromkeys(PAYLOAD_FILES + patched))
            run(["git", "add", "--", *stage_paths], cwd=repo)
            run(["git", "diff", "--cached", "--check"], cwd=repo)
            staged = capture(["git", "diff", "--cached", "--name-only"], cwd=repo)
            staged_paths = {line.strip().replace("\\", "/") for line in staged.splitlines() if line.strip()}
            if staged_paths != set(stage_paths):
                missing = sorted(set(stage_paths) - staged_paths)
                extra = sorted(staged_paths - set(stage_paths))
                raise DeployError(
                    "Staging M61 inatteso. Missing=" + ",".join(missing)
                    + " Extra=" + ",".join(extra)
                )
            run(
                ["git", "commit", "-m", "feat: add Gen4 parallel candidate copyability M61"],
                cwd=repo,
            )
            local_commit_created = True
            commit = capture(["git", "rev-parse", "HEAD"], cwd=repo)
        if capture(["git", "status", "--porcelain"], cwd=repo):
            raise DeployError("Worktree non pulita dopo il commit M61.")
        print(f"M61_COMMIT={commit}")

        remote_deploy_started = True
        deploy_service(repo, BACKEND_SERVICE, "deploy Gen4 parallel candidate copyability M61")
        wait_http(f"{BACKEND_URL}/ready")
        remote_after_backend = remote_alembic_head(database_url)
        if remote_after_backend != TARGET_HEAD:
            raise DeployError(
                f"Railway DB non migrato a M61 dopo deploy backend: {remote_after_backend}"
            )
        print(f"REMOTE_ALEMBIC_AFTER_BACKEND={remote_after_backend}")

        activation_env = os.environ.copy()
        activation_env.update(
            {
                "HELIUS_API_KEY": helius_key,
                "AUTOMATION_API_KEY": automation_key,
                "GEN4_WEBHOOK_SECRET": webhook_secret,
                "GEN4_BACKEND_URL": BACKEND_URL,
                "M61_CANDIDATE_WALLET": EXPECTED_CANDIDATE_WALLET,
            }
        )
        run(
            [sys.executable, repo / "scripts/activate_gen4_parallel_candidate_m61.py"],
            cwd=repo,
            env=activation_env,
        )

        deploy_service(repo, FRONTEND_SERVICE, "deploy Gen4 parallel candidate dashboard M61")
        wait_http(FRONTEND_URL)
        first_status = online_status(automation_key)
        candidate_id = str(
            next(
                item
                for item in first_status["active_campaigns"]
                if item.get("campaign_role") == "QUALIFIED_CANDIDATE"
            ).get("campaign_id")
        )
        print("ONLINE_M61_STATUS=OK")

        run(["git", "push", "origin", "main"], cwd=repo)
        time.sleep(10)
        wait_http(f"{BACKEND_URL}/ready")
        wait_http(FRONTEND_URL)
        remote_after_push = remote_alembic_head(database_url)
        if remote_after_push != TARGET_HEAD:
            raise DeployError("Railway DB non è più alla head M61 dopo il push.")
        second_status = online_status(automation_key)
        candidate_after_push = next(
            item
            for item in second_status["active_campaigns"]
            if item.get("campaign_role") == "QUALIFIED_CANDIDATE"
        )
        if str(candidate_after_push.get("campaign_id")) != candidate_id:
            raise DeployError("Candidate campaign ID cambiato dopo il redeploy GitHub.")
        print("POST_PUSH_M61_VERIFICATION=OK")

        report = write_report(
            backup,
            commit=commit,
            dump=dump,
            candidate_id=candidate_id,
            remote_head_before=remote_before,
            remote_head_after=remote_after_push,
        )
        print("M61_GEN4_PARALLEL_CANDIDATE=INSTALLED_TESTED_DEPLOYED")
        print(f"ALEMBIC_DATABASE={TARGET_HEAD}")
        print(f"PRIMARY_CAMPAIGN_ID={EXPECTED_PRIMARY_CAMPAIGN_ID}")
        print(f"PRIMARY_ANCHOR_PRESERVED={EXPECTED_PRIMARY_ANCHOR}")
        print("PRIMARY_FROZEN_WALLETS=2_UNCHANGED")
        print(f"CANDIDATE_CAMPAIGN_ID={candidate_id}")
        print(f"CANDIDATE_WALLET={EXPECTED_CANDIDATE_WALLET}")
        print("ACTIVE_COPYABILITY_CAMPAIGNS=2")
        print("HELIUS_RAW_WEBHOOK_COUNT=1_EXISTING")
        print("HELIUS_RAW_WEBHOOK_WALLETS=3_UNION")
        print("NO_SIGNER_NO_SIGNATURE_NO_SUBMISSION_NO_PAPER_NO_LIVE")
        print(f"DASHBOARD={FRONTEND_URL}/gen4-forward")
        print(f"REPORT={report}")
        print(f"BACKUP={backup}")
        return 0

    except Exception as error:
        print(f"ERROR={type(error).__name__}: {error}", file=sys.stderr)
        if remote_deploy_started:
            print(
                "REMOTE_EVIDENCE_PRESERVED=YES; lo script di attivazione ripristina "
                "automaticamente webhook/candidata solo se la propria fase fallisce. "
                "Non viene mai fermata la campagna primaria.",
                file=sys.stderr,
            )
        elif local_commit_created:
            print(
                "LOCAL_COMMIT_CREATED_BUT_REMOTE_NOT_STARTED=YES; nessun reset automatico "
                "per non perdere l'audit trail.",
                file=sys.stderr,
            )
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv[1:]:
        porcelain_parser_self_test()
        print("M61_DEPLOY_PORCELAIN_SELF_TEST=PASS")
        raise SystemExit(0)
    if "--local-preflight-only" in sys.argv[1:]:
        raise SystemExit(local_preflight_only(PROJECT_ROOT))
    raise SystemExit(main())
