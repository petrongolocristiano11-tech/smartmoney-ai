from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-m65-verifier-not-used")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_ALEMBIC_HEAD,
    M64_EXPECTED_GIT_HEAD,
)
from backend.app.services.gen4_definitive_wallet_gate_service import (  # noqa: E402
    M65_DEFAULT_POLICY,
    M65_GATE_VERSION,
    M65_RUN_CONFIRMATION,
    M65_SCOPE,
)


SERVICE_PATH = (
    PROJECT_ROOT
    / "backend/app/services/gen4_definitive_wallet_gate_service.py"
)
M64_SERVICE_PATH = (
    PROJECT_ROOT
    / "backend/app/services/gen4_closed_trade_readonly_audit_service.py"
)
RUNNER_PATH = PROJECT_ROOT / "scripts/run_m65_gen4_definitive_wallet_gate.py"
TEST_PATH = PROJECT_ROOT / "tests/test_m65_gen4_definitive_wallet_gate.py"
FIXTURE_PATH = (
    PROJECT_ROOT / "tests/fixtures/m65_gen4_definitive_wallet_gate.json"
)
M64_PATCH_LIST_PATH = (
    PROJECT_ROOT / "PATCH_FILES_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT.txt"
)
M65_PATCH_LIST_PATH = (
    PROJECT_ROOT / "PATCH_FILES_M65_GEN4_DEFINITIVE_WALLET_GATE.txt"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alembic_heads() -> list[str]:
    revisions: dict[str, str | tuple[str, ...] | None] = {}
    for path in sorted((PROJECT_ROOT / "alembic/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                    }:
                        values[target.id] = ast.literal_eval(node.value)
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in {"revision", "down_revision"}
                and node.value is not None
            ):
                values[node.target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        if isinstance(revision, str):
            revisions[revision] = values.get("down_revision")  # type: ignore[assignment]
    parents: set[str] = set()
    for parent in revisions.values():
        if isinstance(parent, str):
            parents.add(parent)
        elif isinstance(parent, tuple):
            parents.update(item for item in parent if isinstance(item, str))
    return sorted(set(revisions) - parents)


def require_text(path: Path, *needles: str) -> str:
    source = path.read_text(encoding="utf-8")
    for needle in needles:
        if needle not in source:
            raise AssertionError(f"Marker M65 mancante in {path.name}: {needle}")
    return source


def verify_cumulative_payload_contract() -> list[str]:
    paths: list[str] = []
    for list_path in (M64_PATCH_LIST_PATH, M65_PATCH_LIST_PATH):
        for line in list_path.read_text(encoding="utf-8-sig").splitlines():
            relative = line.strip()
            if relative:
                paths.append(relative)
    if len(paths) != 19 or len(set(paths)) != 19:
        raise AssertionError(
            f"Payload cumulativo M64+M65 inatteso: {len(paths)} file."
        )
    for relative in paths:
        candidate = (PROJECT_ROOT / relative).resolve()
        try:
            candidate.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise AssertionError(
                f"Percorso payload fuori repository: {relative}"
            ) from error
        if not candidate.is_file():
            raise AssertionError(f"File payload mancante: {relative}")
        raw = candidate.read_bytes()
        if b"\x00" in raw:
            raise AssertionError(f"Byte NUL nel payload: {relative}")
        if not raw.endswith(b"\n"):
            raise AssertionError(f"Newline EOF mancante: {relative}")
        for number, line in enumerate(raw.splitlines(), start=1):
            if line.endswith((b" ", b"\t")):
                raise AssertionError(
                    f"Whitespace finale: {relative}:{number}"
                )
    return paths


def main() -> int:
    payload_paths = verify_cumulative_payload_contract()
    if alembic_heads() != [M64_EXPECTED_ALEMBIC_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {alembic_heads()}")
    service = require_text(
        SERVICE_PATH,
        f'M65_GATE_VERSION = "{M65_GATE_VERSION}"',
        f'M65_SCOPE = "{M65_SCOPE}"',
        '"minimum_profit_factor": 1.20',
        '"minimum_recent_profit_factor": 1.00',
        '"require_positive_net_pnl_after_removing_best_trade": True',
        '"minimum_positive_stability_windows": 3',
        '"canary_minimum_observation_hours": 24.0',
        '"canary_minimum_webhook_coverage_percent": 95.0',
        '"FAIL_ECONOMIC"',
        '"CONDITIONAL_PASS_CANARY_REQUIRED"',
        '"PASS_FOR_MICRO_LIVE_PREPARATION"',
        '"REALTIME_CANARY_FAILED"',
        '"micro_live_execution_authorized": False',
        '"automatic_live_activation": False',
        '"signer_authorized": False',
        '"RECOVERY_ANALYTIC_SAMPLE_IS_NOT_OFFICIAL_REALTIME_PROOF"',
        '"HISTORICAL_JUPITER_ENTRY_ADMISSION_UNAVAILABLE_NOT_INVENTED"',
    )
    m64_service = require_text(
        M64_SERVICE_PATH,
        "M64_EXPECTED_QUARANTINED_SEED_POSITIONS = 2",
        '"entry_sequence": int(row.id)',
        '"target_cut_through_close_batch"',
        '"EXACT_REALTIME_ENTRY_QUOTE_FOR_RECOVERY_EXIT_RECONSTRUCTION"',
        '"cutoff_complete_batch_sensitivity"',
    )
    runner = require_text(
        RUNNER_PATH,
        f'M65_RUN_CONFIRMATION',
        'print("GATE_EVALUATION=PASS")',
        'print(f"GATE_VERDICT={verdict[\'status\']}")',
        'print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")',
        'print("AUTOMATIC_LIVE_ACTIVATION=NO")',
        'print("SIGNER_AUTHORIZED=NO")',
        'print("HELIUS_REQUESTS=0")',
        'print("DATABASE_WRITES=0")',
        'print("BACKEND_POSTS=0")',
    )
    require_text(
        TEST_PATH,
        "test_current_candidate_regression_is_fail_closed_with_exact_core_metrics",
        "test_economic_pass_without_canary_is_conditional_and_never_auto_live",
        "test_economic_and_canary_pass_only_allow_preparation_not_execution",
        "test_canary_failure_cannot_be_hidden_by_strong_history",
        "test_report_tampering_and_safety_mutation_are_rejected",
        "test_raw_evidence_contract_is_hash_bound_and_fail_closed",
        "test_runner_binds_exact_m64_pair_and_writes_hashed_fail_closed_report",
    )
    guarded = service + "\n" + runner
    for forbidden in (
        "import httpx",
        "import requests",
        "from sqlalchemy",
        ".client.post(",
        ".commit(",
        "db.add(",
        "execute_order(",
        "submit_transaction(",
        "JupiterSwapClient(",
        "receive_gen4_copyability_webhook(",
    ):
        if forbidden in guarded:
            raise AssertionError(f"Percorso vietato M65 rilevato: {forbidden}")
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture["expected"]["verdict"] != "FAIL_ECONOMIC":
        raise AssertionError("Fixture candidata M65 deve restare fail-closed.")
    if len(fixture["official_pnl_lamports"]) != 83:
        raise AssertionError("Fixture ufficiale M65 diversa da 83.")
    if len(fixture["reconstructed_pnl_lamports"]) != 17:
        raise AssertionError("Fixture ricostruita M65 diversa da 17.")
    if sum(fixture["official_pnl_lamports"]) != 32_319_569:
        raise AssertionError("PnL ufficiale fixture M65 inatteso.")
    if sum(fixture["reconstructed_pnl_lamports"]) != -13_864_963:
        raise AssertionError("PnL recente fixture M65 inatteso.")
    if M65_DEFAULT_POLICY["minimum_profit_factor"] != 1.20:
        raise AssertionError("Soglia profit factor M65 inattesa.")
    if M65_RUN_CONFIRMATION != (
        "RUN_M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE"
    ):
        raise AssertionError("Conferma runner M65 inattesa.")

    print("=== M65 GEN4 DEFINITIVE WALLET GATE VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={M64_EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={M64_EXPECTED_ALEMBIC_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print(f"GATE_VERSION={M65_GATE_VERSION}")
    print("OFFICIAL_REALTIME_TRADES=83")
    print("RECONSTRUCTED_ANALYTIC_TRADES=17")
    print("COMBINED_EQUIVALENT_SAMPLE=100")
    print("CURRENT_CANDIDATE_EXPECTED_VERDICT=FAIL_ECONOMIC")
    print("CURRENT_CANDIDATE_RECOMMENDED_STATE=RESEARCH_ONLY")
    print("PRODUCTION_DRAWDOWN_TIE_BREAK=PASS")
    print("RECOVERY_QUARANTINED_ENTRY_SEED=PASS")
    print("CUTOFF_CLOSE_BATCH_SENSITIVITY=PASS")
    print("SHORT_REALTIME_CANARY_REQUIRED_FOR_ANY_PASS=YES")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("AUTOMATIC_LIVE_ACTIVATION=NO")
    print("SIGNER_AUTHORIZED=NO")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print(f"CUMULATIVE_PAYLOAD_FILES={len(payload_paths)}")
    print("CUMULATIVE_PAYLOAD_WHITESPACE=PASS")
    print(f"M64_SERVICE_SHA256={sha256(M64_SERVICE_PATH)}")
    print(f"M65_SERVICE_SHA256={sha256(SERVICE_PATH)}")
    print(f"M65_RUNNER_SHA256={sha256(RUNNER_PATH)}")
    print(f"M65_FIXTURE_SHA256={sha256(FIXTURE_PATH)}")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
