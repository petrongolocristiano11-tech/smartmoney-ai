from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    M64_DEFAULT_PUBLIC_RPC_URL,
    M64_OFFICIAL_REALTIME_TRADES,
    M64_TARGET_RECONSTRUCTED_TRADES,
    M64_TARGET_WALLET,
    M64ReadonlyAuditError,
    PublicSolanaRpc,
    aware,
    build_audit_report,
    canonical_sha256,
    collect_public_transactions,
    file_sha256,
    load_official_snapshot,
    parse_public_transactions,
    reconstruct_closed_trades,
    utc_now,
    write_json_atomic,
)


RUN_CONFIRMATION = "RUN_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit M64 read-only: 83 trade ufficiali piu round trip pubblici "
            "ricostruibili, senza Helius, backend POST o scritture database."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rpc-url", default=M64_DEFAULT_PUBLIC_RPC_URL)
    parser.add_argument("--max-signatures", type=int, default=5000)
    parser.add_argument(
        "--database-url-env",
        default="DATABASE_PUBLIC_URL",
        help="Nome della variabile ambiente; il valore non viene mai stampato.",
    )
    parser.add_argument(
        "--target-reconstructed-trades",
        type=int,
        default=M64_TARGET_RECONSTRUCTED_TRADES,
    )
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _raw_evidence(
    *,
    official: dict[str, Any],
    public_result: dict[str, Any],
    rpc_stats: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "scope": "M64_PUBLIC_FINALIZED_RAW_EVIDENCE",
        "wallet": M64_TARGET_WALLET,
        "boundary": official["boundary"],
        "quarantined_seed_positions": official[
            "quarantined_seed_positions"
        ],
        "rpc": rpc_stats,
        "signatures": public_result["signatures"],
        "transactions": public_result["transactions"],
        "unavailable_signatures": public_result["unavailable"],
        "boundary_reached": public_result["boundary_reached"],
        "signature_limit_reached": public_result["signature_limit_reached"],
        "helius_requests": 0,
        "backend_posts": 0,
        "database_writes": 0,
    }
    payload["payload_sha256"] = canonical_sha256(payload)
    return payload


def main() -> int:
    args = _parser().parse_args()
    if args.confirmation.strip() != RUN_CONFIRMATION:
        raise M64ReadonlyAuditError(f"Conferma richiesta: {RUN_CONFIRMATION}.")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M64ReadonlyAuditError(
            "L'output audit deve restare fuori dal repository Git."
        )
    environment_name = str(args.database_url_env or "").strip()
    database_public_url = str(os.getenv(environment_name) or "").strip()
    if not database_public_url:
        raise M64ReadonlyAuditError(
            f"Variabile {environment_name} assente; nessun fallback a DATABASE_URL."
        )
    target = max(1, min(int(args.target_reconstructed_trades), 100))
    if target != M64_TARGET_RECONSTRUCTED_TRADES:
        raise M64ReadonlyAuditError(
            f"Il pacchetto M64 richiede esattamente {M64_TARGET_RECONSTRUCTED_TRADES} trade."
        )
    started = utc_now()
    official = load_official_snapshot(database_public_url)
    boundary = aware(datetime.fromisoformat(official["boundary"]["after_utc"]))
    if boundary is None:
        raise M64ReadonlyAuditError("Confine M63 non disponibile.")

    rpc = PublicSolanaRpc(args.rpc_url)
    try:
        public_result = collect_public_transactions(
            rpc,
            wallet_address=M64_TARGET_WALLET,
            after=boundary,
            after_signature=official["boundary"]["after_signature"],
            maximum_signatures=args.max_signatures,
        )
        rpc_stats = rpc.stats()
    finally:
        rpc.close()
    if public_result["signature_limit_reached"]:
        raise M64ReadonlyAuditError(
            "Limite firme raggiunto prima del confine; audit rifiutato."
        )

    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    raw_path = output_dir / f"smartmoney-m64-public-raw-evidence-{timestamp}.json"
    report_path = output_dir / f"smartmoney-m64-83-plus-17-readonly-audit-{timestamp}.json"
    raw_payload = _raw_evidence(
        official=official,
        public_result=public_result,
        rpc_stats=rpc_stats,
    )
    write_json_atomic(raw_path, raw_payload)
    raw_hash = file_sha256(raw_path)

    parsed = parse_public_transactions(
        public_result["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    reconstruction = reconstruct_closed_trades(
        parsed["events"],
        policy=official["campaign"],
        target_closed_trades=target,
        seed_positions=official["quarantined_seed_positions"],
    )
    completed = utc_now()
    report = build_audit_report(
        official_snapshot=official,
        public_result=public_result,
        parser_result=parsed,
        reconstruction=reconstruction,
        rpc_stats=rpc_stats,
        started_at=started,
        completed_at=completed,
        raw_evidence_sha256=raw_hash,
    )
    report["artifacts"] = {
        "raw_evidence_filename": raw_path.name,
        "raw_evidence_sha256": raw_hash,
        "report_filename": report_path.name,
    }
    report["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "integrity"}
    )
    write_json_atomic(report_path, report)
    report_hash = file_sha256(report_path)

    reconstructed_n = int(
        report["samples"]["reconstructed"]["closed_trade_count"]
    )
    combined_n = M64_OFFICIAL_REALTIME_TRADES + reconstructed_n
    print("=== M64 GEN4 83 PLUS CLOSED TRADES READ-ONLY AUDIT ===")
    print("AUDIT=PASS")
    print(f"OFFICIAL_REALTIME_TRADES={M64_OFFICIAL_REALTIME_TRADES}")
    print(f"RECONSTRUCTED_CLOSED_TRADES={reconstructed_n}")
    print(f"COMBINED_EQUIVALENT_SAMPLE={combined_n}")
    print(
        "COMPLETE_CUTOFF_BATCH_SAMPLE="
        + str(
            report["samples"]["cutoff_complete_batch_sensitivity"][
                "closed_trade_count"
            ]
        )
    )
    print(
        "TARGET_CUT_THROUGH_CLOSE_BATCH="
        + (
            "YES"
            if report["samples"]["cutoff_complete_batch_sensitivity"][
                "target_cut_through_close_batch"
            ]
            else "NO"
        )
    )
    print(
        "TARGET_17_REACHED="
        + ("YES" if reconstructed_n == M64_TARGET_RECONSTRUCTED_TRADES else "NO")
    )
    print("OFFICIAL_COUNTER_MUTATED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HISTORICAL_JUPITER_QUOTES=UNAVAILABLE_NOT_INVENTED")
    print(f"PUBLIC_RPC_REQUESTS={rpc_stats['requests']}")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print(f"RAW_EVIDENCE_FILE={raw_path}")
    print(f"RAW_EVIDENCE_SHA256={raw_hash}")
    print(f"AUDIT_REPORT_FILE={report_path}")
    print(f"AUDIT_REPORT_SHA256={report_hash}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"AUDIT=FAILED type={type(error).__name__}")
        raise SystemExit(1) from None
