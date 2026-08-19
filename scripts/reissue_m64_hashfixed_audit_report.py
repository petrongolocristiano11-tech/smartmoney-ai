from __future__ import annotations

import argparse
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_definitive_wallet_gate_service import (  # noqa: E402
    M65DefinitiveGateError,
    load_json,
    normalize_m64_audit_report,
    verify_raw_evidence,
)


HOTFIX_SCOPE = "M65_HOTFIX1_M64_ENRICHED_TRADE_HASH_REISSUE_READ_ONLY"
RUN_CONFIRMATION = "REISSUE_M64_ENRICHED_TRADE_HASHES_FROM_BOUND_RAW_EVIDENCE"


class M65HashReissueError(RuntimeError):
    pass


def _without(value: dict[str, Any], *fields: str) -> dict[str, Any]:
    excluded = set(fields)
    return {key: item for key, item in value.items() if key not in excluded}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M65HashReissueError(message)


def _valid_final_trade_hash(trade: dict[str, Any]) -> str:
    return canonical_sha256(_without(trade, "evidence_sha256"))


def _legacy_enrichment_hash(trade: dict[str, Any]) -> str:
    scenario_payload = _without(trade, "evidence_sha256", "cost_impact")
    scenario_hash = canonical_sha256(scenario_payload)
    legacy_payload = _without(trade, "evidence_sha256")
    legacy_payload["evidence_sha256"] = scenario_hash
    return canonical_sha256(legacy_payload)


def repair_enriched_trade_hashes(
    report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, int]]:
    repaired = copy.deepcopy(report)
    samples = dict(repaired.get("samples") or {})
    official = list((samples.get("official_realtime") or {}).get("trades") or [])
    reconstructed = list((samples.get("reconstructed") or {}).get("trades") or [])
    supplemental = list(
        (samples.get("cutoff_complete_batch_sensitivity") or {}).get(
            "supplemental_trades"
        )
        or []
    )
    _require(len(official) == 83, "Campione ufficiale diverso da 83.")
    _require(len(reconstructed) == 17, "Campione ricostruito diverso da 17.")

    for index, trade in enumerate(official, start=1):
        _require(
            str(trade.get("evidence_sha256") or "")
            == _valid_final_trade_hash(trade),
            f"Hash ufficiale non valido #{index}; hotfix rifiutato.",
        )

    repaired_count = 0
    already_valid_count = 0
    for label, rows in (
        ("reconstructed", reconstructed),
        ("supplemental", supplemental),
    ):
        for index, trade in enumerate(rows, start=1):
            stored = str(trade.get("evidence_sha256") or "")
            final_hash = _valid_final_trade_hash(trade)
            if stored == final_hash:
                already_valid_count += 1
                continue
            _require(
                stored == _legacy_enrichment_hash(trade),
                f"Hash {label} #{index} non corrisponde al difetto noto; "
                "hotfix rifiutato.",
            )
            trade["evidence_sha256"] = final_hash
            repaired_count += 1

    _require(repaired_count > 0, "Il report non contiene il difetto hash noto.")
    return repaired, {
        "official_valid_count": len(official),
        "repaired_enriched_trade_count": repaired_count,
        "already_valid_enriched_trade_count": already_valid_count,
        "reconstructed_trade_count": len(reconstructed),
        "supplemental_trade_count": len(supplemental),
    }


def reissue_report(
    *,
    audit_path: Path,
    raw_path: Path,
    output_dir: Path,
    reissued_at: datetime | None = None,
) -> tuple[Path, dict[str, Any], dict[str, int]]:
    audit = load_json(audit_path)
    raw = load_json(raw_path)
    integrity = dict(audit.get("integrity") or {})
    expected_report_payload_hash = str(
        integrity.get("report_payload_sha256") or ""
    )
    _require(len(expected_report_payload_hash) == 64, "Hash report M64 assente.")
    _require(
        expected_report_payload_hash
        == canonical_sha256(_without(audit, "integrity")),
        "Hash esterno del report M64 non valido.",
    )
    artifacts = dict(audit.get("artifacts") or {})
    expected_report_name = str(artifacts.get("report_filename") or "")
    _require(
        not expected_report_name or audit_path.name == expected_report_name,
        "Il report selezionato non coincide con il nome dichiarato.",
    )
    expected_raw_name = str(artifacts.get("raw_evidence_filename") or "")
    expected_raw_hash = str(artifacts.get("raw_evidence_sha256") or "")
    _require(raw_path.name == expected_raw_name, "Raw evidence non associato al report.")
    verify_raw_evidence(
        raw,
        expected_file_sha256=expected_raw_hash,
        raw_evidence_path=raw_path,
    )

    fixed, repair = repair_enriched_trade_hashes(audit)
    now = reissued_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / (
        f"smartmoney-m64-83-plus-17-readonly-audit-hashfixed-{timestamp}.json"
    )
    fixed["artifacts"]["report_filename"] = output_path.name
    fixed["hotfix"] = {
        "scope": HOTFIX_SCOPE,
        "reissued_at_utc": now.isoformat(),
        "original_report_filename": audit_path.name,
        "original_report_file_sha256": file_sha256(audit_path),
        "original_report_payload_sha256": expected_report_payload_hash,
        "raw_evidence_filename": raw_path.name,
        "raw_evidence_file_sha256": expected_raw_hash,
        "modified_fields": [
            "samples.reconstructed.trades[*].evidence_sha256",
            (
                "samples.cutoff_complete_batch_sensitivity."
                "supplemental_trades[*].evidence_sha256"
            ),
            "artifacts.report_filename",
            "integrity.report_payload_sha256",
        ],
        **repair,
        "economics_modified": False,
        "official_realtime_counter_modified": False,
        "recovery_counted_as_realtime_proof": False,
    }
    fixed["integrity"]["report_payload_sha256"] = canonical_sha256(
        _without(fixed, "integrity")
    )
    normalize_m64_audit_report(fixed)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_path, fixed)
    return output_path, fixed, repair


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Riemette un report M64 correggendo esclusivamente il difetto noto "
            "dell'hash annidato. Nessuna rete o scrittura production."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--raw-evidence", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.confirmation.strip() != RUN_CONFIRMATION:
        raise M65HashReissueError(f"Conferma richiesta: {RUN_CONFIRMATION}.")
    audit_path = Path(args.audit_report).expanduser().resolve()
    raw_path = Path(args.raw_evidence).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    try:
        output_dir.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    else:
        raise M65HashReissueError("L'output deve restare fuori dal repository Git.")
    if not audit_path.is_file() or not raw_path.is_file():
        raise M65HashReissueError("Report M64 o raw evidence non trovato.")
    output_path, _, repair = reissue_report(
        audit_path=audit_path,
        raw_path=raw_path,
        output_dir=output_dir,
    )
    print("=== M65 HOTFIX1 M64 EVIDENCE HASH REISSUE ===")
    print("M64_HASH_REISSUE=PASS")
    print("OFFICIAL_REALTIME_TRADES=83")
    print("RECONSTRUCTED_CLOSED_TRADES=17")
    print(
        "REPAIRED_ENRICHED_TRADE_HASHES="
        + str(repair["repaired_enriched_trade_count"])
    )
    print("ECONOMICS_MODIFIED=NO")
    print("OFFICIAL_COUNTER_MUTATED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("NETWORK_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print(f"REISSUED_AUDIT_REPORT_FILE={output_path}")
    print(f"REISSUED_AUDIT_REPORT_SHA256={file_sha256(output_path)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M64_HASH_REISSUE=FAILED "
            f"type={type(error).__name__} message={message}",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
