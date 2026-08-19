from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_definitive_discovery_rotation_service import (  # noqa: E402
    M72DiscoveryRotationError,
    M72_RUN_CONFIRMATION,
    build_rotation_report,
    validate_acquisition_plan,
    validate_rotation_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M72 read-only: decide la rotazione definitiva dei candidati M71 e "
            "prepara, senza eseguirlo, il piano di acquisizione controllata."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--m71-report", required=True)
    parser.add_argument("--updated-m67-report", required=True)
    parser.add_argument("--updated-rpc-evidence", required=True)
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _load_json(path_text: str, *, label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise M72DiscoveryRotationError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M72DiscoveryRotationError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M72DiscoveryRotationError(f"Root {label} non oggetto: {path.name}.")
    return path, value


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M72_RUN_CONFIRMATION:
        raise M72DiscoveryRotationError(
            f"Conferma richiesta: {M72_RUN_CONFIRMATION}."
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M72DiscoveryRotationError("Output M72 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    m71_path, m71_report = _load_json(args.m71_report, label="Report M71")
    m67_path, m67_report = _load_json(
        args.updated_m67_report,
        label="Report M67-M70 aggiornato",
    )
    rpc_path, rpc_evidence = _load_json(
        args.updated_rpc_evidence,
        label="Evidenza RPC aggiornata",
    )
    started = datetime.now(timezone.utc)
    report, plan = build_rotation_report(
        m71_report,
        m67_report,
        rpc_evidence,
        evaluated_at=started,
    )
    validate_rotation_report(report)
    validate_acquisition_plan(plan)

    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / (
        f"smartmoney-m72-definitive-discovery-rotation-report-{timestamp}.json"
    )
    plan_path = output_dir / (
        "smartmoney-m72-controlled-new-wallet-acquisition-plan-disarmed-"
        f"{timestamp}.json"
    )
    write_json_atomic(report_path, report)
    write_json_atomic(plan_path, plan)

    summary = dict(report.get("rotation_summary") or {})
    provider = dict(plan.get("provider") or {})
    decision = dict(report.get("decision") or {})
    print("=== M72 DEFINITIVE DISCOVERY ROTATION READ-ONLY ===")
    print("M72_ROTATION=PASS")
    print(f"INPUT_M71_FILE_SHA256={file_sha256(m71_path)}")
    print(f"INPUT_UPDATED_M67_FILE_SHA256={file_sha256(m67_path)}")
    print(f"INPUT_UPDATED_RPC_FILE_SHA256={file_sha256(rpc_path)}")
    print(f"ACTIVE_WALLETS_REVIEWED={summary.get('active_wallets_reviewed', 0)}")
    print(f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('qualified_pending_short_canary', 0)}")
    print(f"OBSERVE_ONLY={summary.get('observe_only', 0)}")
    print(f"RETIRED_FROM_PROMOTION={summary.get('retired_from_promotion', 0)}")
    print(f"RESEARCH_ONLY_LOCKED={summary.get('research_only_locked', 0)}")
    print(
        "RERUN_M71_SAME_INPUTS="
        + ("YES" if decision.get("rerun_m71_same_inputs_recommended") else "NO")
    )
    print(
        "NEW_WALLET_DISCOVERY_REQUIRED="
        + ("YES" if decision.get("new_wallet_discovery_required") else "NO")
    )
    print(f"CONTROLLED_HELIUS_MAXIMUM_REQUESTS={provider.get('maximum_requests', 0)}")
    print(f"CONTROLLED_HELIUS_CREDIT_CAP={provider.get('credit_cap', 0)}")
    print(f"CONTROLLED_HELIUS_RETRIES={provider.get('retries', 0)}")
    print("CONTROLLED_DISCOVERY_PLAN=PREPARED_DISARMED")
    print("CONTROLLED_DISCOVERY_EXECUTION_AUTHORIZED=NO")
    print("CONTROLLED_DISCOVERY_EXECUTION_PERFORMED=NO")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("NETWORK_REQUESTS=0")
    print("PUBLIC_RPC_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("HELIUS_CREDITS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print(f"M72_ROTATION_REPORT_FILE={report_path}")
    print(f"M72_ROTATION_REPORT_SHA256={file_sha256(report_path)}")
    print(f"M72_ACQUISITION_PLAN_FILE={plan_path}")
    print(f"M72_ACQUISITION_PLAN_SHA256={file_sha256(plan_path)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M72_ROTATION=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        raise SystemExit(1) from None
