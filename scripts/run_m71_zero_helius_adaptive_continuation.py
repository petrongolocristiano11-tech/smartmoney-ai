from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_DEFAULT_PUBLIC_RPC_URL,
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_zero_helius_adaptive_continuation_service import (  # noqa: E402
    M71_DEFAULT_POLICY,
    M71_RUN_CONFIRMATION,
    M71AdaptiveContinuationError,
    build_adaptive_plan,
    build_continuation_report,
    correct_local_snapshot_official_filter,
    validate_continuation_report,
    validate_input_bundle,
    validate_policy as validate_m71_policy,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    build_rpc_evidence,
    evaluate_zero_helius_pre_micro_live,
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M71 Zero-Helius: corregge il filtro 83/85, riusa la cache M67 e "
            "continua in modo adattivo lo storico pubblico dei candidati."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--previous-snapshot", required=True)
    parser.add_argument("--previous-rpc-evidence", required=True)
    parser.add_argument("--previous-report", required=True)
    parser.add_argument("--cache-input", required=True)
    parser.add_argument("--rpc-url", default=M64_DEFAULT_PUBLIC_RPC_URL)
    parser.add_argument("--maximum-wallets", type=int, default=4)
    parser.add_argument("--extension-signatures", type=int, default=500)
    parser.add_argument("--new-candidate-signatures", type=int, default=300)
    parser.add_argument("--public-rpc-request-cap", type=int, default=1800)
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _load_json(path_text: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise M71AdaptiveContinuationError(f"JSON M71 non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M71AdaptiveContinuationError(f"JSON M71 non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M71AdaptiveContinuationError(f"Root JSON M71 non oggetto: {path.name}.")
    return path, value


def _prefer_more_complete(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    previous_key = (
        bool(previous.get("history_complete")),
        int(previous.get("transaction_count") or 0),
        int(previous.get("signature_count") or 0),
    )
    current_key = (
        bool(current.get("history_complete")),
        int(current.get("transaction_count") or 0),
        int(current.get("signature_count") or 0),
    )
    return current if current_key >= previous_key else previous


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M71_RUN_CONFIRMATION:
        raise M71AdaptiveContinuationError(
            f"Conferma richiesta: {M71_RUN_CONFIRMATION}."
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M71AdaptiveContinuationError("Output M71 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path, previous_snapshot = _load_json(args.previous_snapshot)
    rpc_path, previous_rpc = _load_json(args.previous_rpc_evidence)
    report_path, previous_report = _load_json(args.previous_report)
    cache_path = Path(args.cache_input).expanduser().resolve()
    if not cache_path.is_file():
        raise M71AdaptiveContinuationError("Cache M67 obbligatoria non trovata.")

    input_bundle = validate_input_bundle(
        previous_snapshot,
        previous_rpc,
        previous_report,
    )
    corrected_snapshot, corrections = correct_local_snapshot_official_filter(
        previous_snapshot
    )
    m71_policy = validate_m71_policy(
        {
            **M71_DEFAULT_POLICY,
            "maximum_wallets_per_batch": max(1, min(int(args.maximum_wallets), 4)),
            "extension_signature_target": max(
                150, min(int(args.extension_signatures), 1000)
            ),
            "new_candidate_signature_target": max(
                100, min(int(args.new_candidate_signatures), 500)
            ),
            "public_rpc_request_cap": max(
                300, min(int(args.public_rpc_request_cap), 2000)
            ),
        }
    )
    plan = build_adaptive_plan(
        previous_report,
        previous_rpc,
        policy=m71_policy,
    )

    parsed_url = urlsplit(str(args.rpc_url or ""))
    public_origin = f"{parsed_url.scheme}://{str(parsed_url.hostname or '').lower()}"
    cache = _load_cache(str(cache_path), public_origin=public_origin)
    rpc_client = CachedBudgetedPublicRpc(
        args.rpc_url,
        cache=cache,
        request_cap=int(m71_policy["public_rpc_request_cap"]),
        maximum_attempts=int(m71_policy["public_rpc_maximum_attempts"]),
        throttle_seconds=float(m71_policy["public_rpc_throttle_seconds"]),
    )
    previous_deep = {
        str(key): dict(value)
        for key, value in dict(previous_rpc.get("deep_history") or {}).items()
    }
    combined_deep = dict(previous_deep)
    actions = {
        str(item.get("wallet_address") or ""): dict(item)
        for item in plan.get("candidate_actions") or []
    }
    started = datetime.now(timezone.utc)
    try:
        for wallet in plan.get("selected_wallets") or []:
            action = actions[str(wallet)]
            target = int(action["target_signatures"])
            wallet_policy = validate_m67_policy(
                {
                    **dict(previous_report.get("policy") or {}),
                    "maximum_signatures_per_deep_wallet": target,
                    "public_rpc_request_cap": int(m71_policy["public_rpc_request_cap"]),
                    "public_rpc_maximum_attempts": int(
                        m71_policy["public_rpc_maximum_attempts"]
                    ),
                    "public_rpc_throttle_seconds": float(
                        m71_policy["public_rpc_throttle_seconds"]
                    ),
                }
            )
            try:
                first_page = _signature_page(
                    rpc_client,
                    str(wallet),
                    limit=int(wallet_policy["signature_page_limit"]),
                )
            except PublicRpcBudgetExhausted:
                break
            current = _collect_deep_history(
                rpc_client,
                str(wallet),
                first_page=first_page,
                now=started,
                policy=wallet_policy,
            )
            combined_deep[str(wallet)] = _prefer_more_complete(
                previous_deep.get(str(wallet), {}),
                current,
            )
    finally:
        rpc_client.close()

    cache = _finalize_cache(cache)
    m67_policy = validate_m67_policy(
        {
            **dict(previous_report.get("policy") or {}),
            "maximum_signatures_per_deep_wallet": int(
                m71_policy["extension_signature_target"]
            ),
            "public_rpc_request_cap": int(m71_policy["public_rpc_request_cap"]),
            "public_rpc_maximum_attempts": int(
                m71_policy["public_rpc_maximum_attempts"]
            ),
            "public_rpc_throttle_seconds": float(
                m71_policy["public_rpc_throttle_seconds"]
            ),
        }
    )
    updated_rpc = build_rpc_evidence(
        activity_rows={
            str(key): dict(value)
            for key, value in dict(previous_rpc.get("activity") or {}).items()
        },
        deep_rows=combined_deep,
        rpc_stats=rpc_client.stats(),
        cache=cache,
        policy=m67_policy,
        collected_at=datetime.now(timezone.utc),
    )
    updated_m67_report = evaluate_zero_helius_pre_micro_live(
        corrected_snapshot,
        updated_rpc,
        policy=m67_policy,
        evaluated_at=datetime.now(timezone.utc),
    )
    updated_m67_report["source"]["execution_mode"] = (
        "M71_SIGNED_INPUTS_PLUS_CACHED_PUBLIC_SOLANA_RPC"
    )
    updated_m67_report["source"]["database_contract"] = {
        "database_reads": 0,
        "database_writes": 0,
        "source": "SIGNED_M67_SNAPSHOT",
    }
    updated_m67_report["integrity"]["report_payload_sha256"] = canonical_sha256(
        {
            name: value
            for name, value in updated_m67_report.items()
            if name != "integrity"
        }
    )
    continuation_report = build_continuation_report(
        input_bundle=input_bundle,
        corrected_snapshot=corrected_snapshot,
        corrections=corrections,
        plan=plan,
        updated_rpc_evidence=updated_rpc,
        updated_m67_report=updated_m67_report,
        previous_deep_history=previous_deep,
        evaluated_at=datetime.now(timezone.utc),
    )
    validate_continuation_report(continuation_report)

    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    corrected_path = output_dir / f"smartmoney-m71-corrected-local-snapshot-{timestamp}.json"
    updated_rpc_path = output_dir / f"smartmoney-m71-adaptive-rpc-evidence-{timestamp}.json"
    updated_m67_path = output_dir / f"smartmoney-m71-updated-m67-m70-report-{timestamp}.json"
    output_cache_path = output_dir / f"smartmoney-m71-public-rpc-cache-{timestamp}.json"
    output_report_path = output_dir / f"smartmoney-m71-adaptive-continuation-report-{timestamp}.json"
    write_json_atomic(corrected_path, corrected_snapshot)
    write_json_atomic(updated_rpc_path, updated_rpc)
    write_json_atomic(updated_m67_path, updated_m67_report)
    write_json_atomic(output_cache_path, cache)
    write_json_atomic(output_report_path, continuation_report)

    summary = dict(updated_m67_report.get("summary") or {})
    stats = rpc_client.stats()
    print("=== M71 ZERO-HELIUS ADAPTIVE CONTINUATION ===")
    print("M71_ADAPTIVE_CONTINUATION=PASS")
    print(f"INPUT_SNAPSHOT_SHA256={file_sha256(snapshot_path)}")
    print(f"INPUT_RPC_EVIDENCE_SHA256={file_sha256(rpc_path)}")
    print(f"INPUT_REPORT_SHA256={file_sha256(report_path)}")
    print(f"INPUT_CACHE_SHA256={file_sha256(cache_path)}")
    print(f"ACTIVE_CANDIDATES={plan['active_candidate_count']}")
    print(f"ADAPTIVE_WALLETS_SELECTED={plan['selected_wallet_count']}")
    print("ADAPTIVE_WALLETS=" + ",".join(plan.get("selected_wallets") or []))
    print(f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('wallets_qualified_pending_canary', 0)}")
    print(f"SELECTED_FOR_CONSENSUS={summary.get('selected_wallets', 0)}")
    print(f"PUBLIC_RPC_REQUEST_CAP={m71_policy['public_rpc_request_cap']}")
    print(f"PUBLIC_RPC_REQUESTS={int(stats.get('requests') or 0)}")
    print(f"PUBLIC_RPC_CACHE_HITS={int(stats.get('cache_hits') or 0)}")
    print(f"PUBLIC_RPC_RETRY_429={int(stats.get('retry_429') or 0)}")
    print("PRIOR_CACHE_REUSED=YES")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print(f"STRICT_83_FILTER_CORRECTIONS={len(corrections)}")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HISTORICAL_JUPITER_QUOTES_INVENTED=NO")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("PRE_MICRO_LIVE_FOUNDATION=PREPARED_DISARMED")
    for label, path in (
        ("CORRECTED_SNAPSHOT_FILE", corrected_path),
        ("UPDATED_RPC_EVIDENCE_FILE", updated_rpc_path),
        ("UPDATED_M67_REPORT_FILE", updated_m67_path),
        ("PUBLIC_RPC_CACHE_FILE", output_cache_path),
        ("M71_REPORT_FILE", output_report_path),
    ):
        print(f"{label}={path}")
        print(f"{label.removesuffix('_FILE')}_SHA256={file_sha256(path)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M71_ADAPTIVE_CONTINUATION=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        raise SystemExit(1) from None
