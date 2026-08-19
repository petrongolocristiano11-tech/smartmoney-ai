from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_definitive_wallet_gate_service import (  # noqa: E402
    M65DefinitiveGateError,
    M65_RUN_CONFIRMATION,
    evaluate_definitive_wallet_gate,
    load_json,
    verify_raw_evidence,
    write_json_atomic,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    canonical_sha256,
    file_sha256,
    utc_now,
)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Gate M65 deterministico e read-only sul report M64 83+17. "
            "Non effettua rete, database, Jupiter, paper o LIVE."
        )
    )
    result.add_argument("--confirmation", default="")
    result.add_argument("--audit-report", required=True)
    result.add_argument("--raw-evidence", required=True)
    result.add_argument("--canary-evidence", default="")
    result.add_argument("--output-dir", required=True)
    return result


def outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def main() -> int:
    args = parser().parse_args()
    if args.confirmation.strip() != M65_RUN_CONFIRMATION:
        raise M65DefinitiveGateError(
            f"Conferma richiesta: {M65_RUN_CONFIRMATION}."
        )
    audit_path = Path(args.audit_report).expanduser().resolve()
    raw_path = Path(args.raw_evidence).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not outside_project(output_dir):
        raise M65DefinitiveGateError(
            "L'output M65 deve essere salvato fuori dal repository Git."
        )
    if not audit_path.is_file() or not raw_path.is_file():
        raise M65DefinitiveGateError("Report M64 o raw evidence non trovato.")
    audit = load_json(audit_path)
    raw = load_json(raw_path)
    artifacts = dict(audit.get("artifacts") or {})
    expected_raw_hash = str(artifacts.get("raw_evidence_sha256") or "")
    if len(expected_raw_hash) != 64:
        raise M65DefinitiveGateError(
            "Il report M64 non contiene lo SHA-256 del raw evidence."
        )
    expected_raw_name = str(artifacts.get("raw_evidence_filename") or "")
    if expected_raw_name and raw_path.name != expected_raw_name:
        raise M65DefinitiveGateError(
            "Il raw evidence selezionato non coincide con il report M64."
        )
    raw_verification = verify_raw_evidence(
        raw,
        expected_file_sha256=expected_raw_hash,
        raw_evidence_path=raw_path,
    )
    canary = None
    if str(args.canary_evidence or "").strip():
        canary_path = Path(args.canary_evidence).expanduser().resolve()
        if not canary_path.is_file():
            raise M65DefinitiveGateError("Canary evidence non trovato.")
        canary = load_json(canary_path)
    evaluated_at = utc_now()
    result = evaluate_definitive_wallet_gate(
        audit,
        canary_evidence=canary,
        evaluated_at=evaluated_at,
    )
    result["raw_evidence_verification"] = raw_verification
    result["integrity"]["gate_payload_sha256"] = canonical_sha256(
        {key: value for key, value in result.items() if key != "integrity"}
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = evaluated_at.strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / (
        f"smartmoney-m65-definitive-wallet-gate-{timestamp}.json"
    )
    write_json_atomic(output_path, result)
    output_hash = file_sha256(output_path)

    verdict = result["verdict"]
    candidate = result["candidate"]
    print("=== M65 GEN4 DEFINITIVE WALLET QUALIFICATION GATE ===")
    print("GATE_EVALUATION=PASS")
    print(f"GATE_VERDICT={verdict['status']}")
    print(f"CANDIDATE_STATE={candidate['recommended_state']}")
    print("OFFICIAL_REALTIME_TRADES=83")
    print("RECONSTRUCTED_ANALYTIC_TRADES=17")
    print("COMBINED_EQUIVALENT_SAMPLE=100")
    print(
        "ECONOMIC_FAILURE_REASONS="
        + ",".join(result["economic_failure_reasons"])
    )
    print(f"REALTIME_CANARY={result['canary']['status']}")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("AUTOMATIC_LIVE_ACTIVATION=NO")
    print("SIGNER_AUTHORIZED=NO")
    print("OFFICIAL_COUNTER_MUTATED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print(f"GATE_REPORT_FILE={output_path}")
    print(f"GATE_REPORT_SHA256={output_hash}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "GATE_EVALUATION=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        raise SystemExit(1) from None
