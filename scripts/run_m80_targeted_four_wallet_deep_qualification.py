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
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_targeted_deep_qualification_service import (  # noqa: E402
    MAX_SIGNATURES_BY_WALLET,
    M80_CONFIRMATION,
    M80_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
    M80_PUBLIC_RPC_REQUEST_CAP,
    M80_PUBLIC_RPC_THROTTLE_SECONDS,
    M80_SCOPE,
    M80_VERSION,
    TARGET_WALLETS,
    M80DeepQualificationError,
    build_candidate_result,
    build_final_report,
    build_model_policy,
    validate_final_report,
    validate_sources,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import (  # noqa: E402
    CachedBudgetedPublicRpc,
    PublicRpcBudgetExhausted,
    _collect_deep_history,
    _finalize_cache,
    _load_cache,
    _signature_page,
)

PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
STATE_SCHEMA = "SMARTMONEY_M80_TARGETED_DEEP_QUALIFICATION_STATE_V1"

EXPECTED_M66_REPORT_SHA256 = "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
EXPECTED_M73_REPORT_SHA256 = "adf92b8b58fd683705bf8adfff1d8ae0bd5b90ae3c6626e61103f671a7132fea"
EXPECTED_M73_BASE_CACHE_SHA256 = "c4f3b4e0669363d90eb9c4f31c3725d476eeec6a84504867fd02a3e724740608"
EXPECTED_M79_REPORT_SHA256 = "ad717ae9a643ec5e9db8946e698416701b896a44ffd2844a4ab79801305f2bbf"
EXPECTED_M79_DELTA_CACHE_SHA256 = "07ce800f6a2c71e622b2ced630d656ccc99d4a997652818896a752a9d7591dcf"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="M80 targeted four-wallet deep Gen4 qualification, zero Helius.")
    p.add_argument("--confirmation", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--m66-report", required=True)
    p.add_argument("--m73-report", required=True)
    p.add_argument("--m73-base-cache", required=True)
    p.add_argument("--m79-report", required=True)
    p.add_argument("--m79-delta-cache", required=True)
    p.add_argument("--rpc-url", default=PUBLIC_RPC_URL)
    return p


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise M80DeepQualificationError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M80DeepQualificationError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M80DeepQualificationError(f"Root {label} non oggetto.")
    return value


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _state_payload(state: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in state.items() if key != "integrity"}


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = _state_payload(state)
    result = dict(payload)
    result["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return result


def _validate_state(state: dict[str, Any], input_hashes: dict[str, str]) -> dict[str, Any]:
    if state.get("schema") != STATE_SCHEMA:
        raise M80DeepQualificationError("Schema stato M80 inatteso.")
    payload = _state_payload(state)
    expected = str(dict(state.get("integrity") or {}).get("payload_sha256") or "")
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M80DeepQualificationError("Hash stato M80 non valido.")
    if dict(state.get("input_hashes") or {}) != input_hashes:
        raise M80DeepQualificationError("Input M80 diversi dallo stato di resume.")
    return state


def _merge_layer(base: dict[str, Any], layer: dict[str, Any]) -> dict[str, Any]:
    if base.get("schema") != layer.get("schema") or base.get("public_origin") != layer.get("public_origin"):
        raise M80DeepQualificationError("Layer cache M80 incompatibili.")
    merged = {
        "schema": base.get("schema"),
        "public_origin": base.get("public_origin"),
        "entries": dict(base.get("entries") or {}),
    }
    for key, value in dict(layer.get("entries") or {}).items():
        old = dict(merged["entries"].get(key) or {})
        new = dict(value or {})
        if old and old.get("request") != new.get("request"):
            raise M80DeepQualificationError("Collisione request contract tra cache.")
        merged["entries"][key] = new
    return merged


def _empty_cache(public_origin: str) -> dict[str, Any]:
    return _finalize_cache({
        "schema": "SMARTMONEY_M67_ZERO_HELIUS_PUBLIC_RPC_CACHE_V1",
        "public_origin": public_origin,
        "entries": {},
    })


def _delta_against(before_m80: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    base_entries = dict(before_m80.get("entries") or {})
    current_entries = dict(current.get("entries") or {})
    changed = {
        key: value
        for key, value in current_entries.items()
        if key not in base_entries or base_entries.get(key) != value
    }
    return _finalize_cache({
        "schema": current.get("schema"),
        "public_origin": current.get("public_origin"),
        "entries": changed,
    })


def _signature_request_key(public_origin: str, wallet: str) -> str:
    request_contract = {
        "public_origin": public_origin,
        "method": "getSignaturesForAddress",
        "params": [wallet, {"commitment": "finalized", "limit": 100}],
    }
    return canonical_sha256(request_contract)


def _checkpoint(
    *,
    state: dict[str, Any],
    state_path: Path,
    before_m80_cache: dict[str, Any],
    working_cache: dict[str, Any],
    delta_path: Path,
    rpc: CachedBudgetedPublicRpc,
) -> None:
    delta = _delta_against(before_m80_cache, working_cache)
    write_json_atomic(delta_path, delta)
    state["delta_cache_sha256"] = file_sha256(delta_path)
    stats = rpc.stats()
    prior = dict(state.get("rpc_totals_before_process") or {})
    state["rpc_totals"] = {
        key: int(prior.get(key) or 0) + int(stats.get(key) or 0)
        for key in ("requests", "cache_hits", "retry_429", "retry_5xx", "retry_network")
    }
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(state_path, _seal_state(state))


def _run_wallet(
    *,
    rpc: CachedBudgetedPublicRpc,
    wallet: str,
    maximum_signatures: int,
    started: datetime,
    m66_candidate: dict[str, Any],
    force_latest_refresh: bool,
) -> dict[str, Any]:
    if force_latest_refresh:
        key = _signature_request_key(rpc.public_origin, wallet)
        rpc.cache.setdefault("entries", {}).pop(key, None)
    first_page = _signature_page(rpc, wallet, limit=100)
    policy = build_model_policy(maximum_signatures=maximum_signatures)
    deep = _collect_deep_history(
        rpc,
        wallet,
        first_page=first_page,
        now=started,
        policy=policy,
    )
    if deep.get("public_rpc_budget_exhausted"):
        raise PublicRpcBudgetExhausted(f"Cap RPC M80 durante wallet={wallet}.")
    return build_candidate_result(
        wallet,
        deep,
        m66_candidate=m66_candidate,
        policy=policy,
    )


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M80_CONFIRMATION:
        raise M80DeepQualificationError(f"Conferma richiesta: {M80_CONFIRMATION}.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M80DeepQualificationError("Output M80 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlsplit(str(args.rpc_url or "").strip())
    if (
        parsed.scheme.lower() != "https"
        or str(parsed.hostname or "").lower() != "api.mainnet-beta.solana.com"
        or parsed.query
        or parsed.username
        or parsed.password
    ):
        raise M80DeepQualificationError("M80 accetta solo RPC pubblico Solana ufficiale senza credenziali/query.")
    public_origin = PUBLIC_RPC_URL

    paths = {
        "m66_report": Path(args.m66_report).expanduser().resolve(),
        "m73_report": Path(args.m73_report).expanduser().resolve(),
        "m73_base_cache": Path(args.m73_base_cache).expanduser().resolve(),
        "m79_report": Path(args.m79_report).expanduser().resolve(),
        "m79_delta_cache": Path(args.m79_delta_cache).expanduser().resolve(),
    }
    expected_hashes = {
        "m66_report": EXPECTED_M66_REPORT_SHA256,
        "m73_report": EXPECTED_M73_REPORT_SHA256,
        "m73_base_cache": EXPECTED_M73_BASE_CACHE_SHA256,
        "m79_report": EXPECTED_M79_REPORT_SHA256,
        "m79_delta_cache": EXPECTED_M79_DELTA_CACHE_SHA256,
    }
    input_hashes: dict[str, str] = {}
    for label, path in paths.items():
        actual = file_sha256(path) if path.is_file() else ""
        if actual != expected_hashes[label]:
            raise M80DeepQualificationError(f"SHA input M80 inatteso: {label}.")
        input_hashes[label + "_sha256"] = actual

    m66 = _load_json(paths["m66_report"], "Report M66")
    m73 = _load_json(paths["m73_report"], "Report M73")
    m79 = _load_json(paths["m79_report"], "Report M79")
    m66_candidates = validate_sources(m66, m73, m79)

    base = _load_cache(str(paths["m73_base_cache"]), public_origin=public_origin)
    m79_delta = _load_cache(str(paths["m79_delta_cache"]), public_origin=public_origin)
    before_m80 = _merge_layer(base, m79_delta)

    suffix = EXPECTED_M79_REPORT_SHA256[:16]
    state_path = output_dir / f"smartmoney-m80-targeted-deep-state-{suffix}.json"
    delta_path = output_dir / f"smartmoney-m80-public-rpc-delta-cache-{suffix}.json"
    print(f"M80_STATE_FILE={state_path}")
    print(f"M80_DELTA_CACHE_FILE={delta_path}")

    if delta_path.is_file():
        m80_delta = _load_cache(str(delta_path), public_origin=public_origin)
    else:
        m80_delta = _empty_cache(public_origin)
    working = _merge_layer(before_m80, m80_delta)
    m80_delta_keys = set(dict(m80_delta.get("entries") or {}))

    if state_path.is_file():
        state = _validate_state(_load_json(state_path, "Stato M80"), input_hashes)
        if state.get("status") == "COMPLETED":
            report_path = Path(str(state.get("report_file") or ""))
            if report_path.is_file():
                print("M80_TARGETED_DEEP_QUALIFICATION=ALREADY_COMPLETED")
                print(f"M80_REPORT_FILE={report_path}")
                print(f"M80_REPORT_SHA256={file_sha256(report_path)}")
                print(f"M80_DELTA_CACHE_FILE={delta_path}")
                print(f"M80_DELTA_CACHE_SHA256={file_sha256(delta_path)}")
                print("HELIUS_REQUESTS=0")
                print("HELIUS_CREDITS=0")
                return 0
            raise M80DeepQualificationError("Stato M80 COMPLETED ma report assente.")
        started = datetime.fromisoformat(str(state["started_at_utc"]).replace("Z", "+00:00"))
        completed_results = dict(state.get("results") or {})
        prior_totals = dict(state.get("rpc_totals") or {})
    else:
        started = datetime.now(timezone.utc)
        completed_results = {}
        prior_totals = {}
        state = {
            "schema": STATE_SCHEMA,
            "version": M80_VERSION,
            "scope": M80_SCOPE,
            "status": "RUNNING",
            "started_at_utc": started.isoformat(),
            "updated_at_utc": started.isoformat(),
            "input_hashes": input_hashes,
            "results": {},
            "rpc_totals": {},
            "rpc_totals_before_process": {},
            "delta_cache_sha256": None,
            "report_file": None,
            "report_sha256": None,
        }

    state["rpc_totals_before_process"] = prior_totals
    rpc = CachedBudgetedPublicRpc(
        str(args.rpc_url),
        cache=working,
        request_cap=M80_PUBLIC_RPC_REQUEST_CAP,
        maximum_attempts=M80_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
        throttle_seconds=M80_PUBLIC_RPC_THROTTLE_SECONDS,
    )

    print("=== M80 TARGETED FOUR-WALLET ZERO-HELIUS DEEP QUALIFICATION ===")
    print("M66_REEXECUTION=NO")
    print("HELIUS_REQUESTS_AUTHORIZED=0")
    print("HELIUS_CREDITS_AUTHORIZED=0")
    print(f"TARGET_WALLETS={len(TARGET_WALLETS)}")
    print(f"PUBLIC_RPC_REQUEST_CAP_PER_PROCESS={M80_PUBLIC_RPC_REQUEST_CAP}")
    print(f"PUBLIC_RPC_THROTTLE_SECONDS={M80_PUBLIC_RPC_THROTTLE_SECONDS}")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")

    try:
        for index, wallet in enumerate(TARGET_WALLETS, start=1):
            if wallet in completed_results:
                row = dict(completed_results[wallet])
                print(f"M80_WALLET_RESUME_SKIP={index}/4:{wallet};disposition={row.get('disposition')}")
                continue
            maximum = int(MAX_SIGNATURES_BY_WALLET[wallet])
            print(f"M80_WALLET_START={index}/4:{wallet};max_signatures={maximum}")
            first_key = _signature_request_key(public_origin, wallet)
            force_refresh = first_key not in m80_delta_keys
            row = _run_wallet(
                rpc=rpc,
                wallet=wallet,
                maximum_signatures=maximum,
                started=started,
                m66_candidate=m66_candidates[wallet],
                force_latest_refresh=force_refresh,
            )
            completed_results[wallet] = row
            state["results"] = completed_results
            _checkpoint(
                state=state,
                state_path=state_path,
                before_m80_cache=before_m80,
                working_cache=working,
                delta_path=delta_path,
                rpc=rpc,
            )
            print(
                "M80_WALLET_DONE="
                f"{wallet};disposition={row['disposition']};closed={row['closed_trade_count']};"
                f"days={row['history_span_days']};pf={row['profit_factor']};net={row['net_pnl_sol']};"
                f"wr={row['win_rate_percent']};dd={row['maximum_drawdown_percent']};"
                f"open={row['open_positions']};history_complete={str(row['history_complete']).upper()}"
            )
    finally:
        rpc.close()

    if set(completed_results) != set(TARGET_WALLETS):
        raise M80DeepQualificationError("M80 terminato senza tutti i quattro risultati.")

    final_delta = _delta_against(before_m80, working)
    write_json_atomic(delta_path, final_delta)
    delta_sha = file_sha256(delta_path)
    stats = rpc.stats()
    totals = {
        key: int(prior_totals.get(key) or 0) + int(stats.get(key) or 0)
        for key in ("requests", "cache_hits", "retry_429", "retry_5xx", "retry_network")
    }
    totals.update({
        "public_origin": public_origin,
        "request_cap_per_process": M80_PUBLIC_RPC_REQUEST_CAP,
        "maximum_attempts": M80_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
        "throttle_seconds": M80_PUBLIC_RPC_THROTTLE_SECONDS,
        "helius_requests": 0,
    })
    completed_at = datetime.now(timezone.utc)
    report = build_final_report(
        input_hashes=input_hashes,
        started_at_utc=started.isoformat(),
        completed_at_utc=completed_at.isoformat(),
        results=[completed_results[w] for w in TARGET_WALLETS],
        delta_cache_sha256=delta_sha,
        rpc_stats=totals,
    )
    validate_final_report(report)
    report_path = output_dir / f"smartmoney-m80-targeted-four-wallet-deep-qualification-{completed_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    write_json_atomic(report_path, report)

    state.update({
        "status": "COMPLETED",
        "updated_at_utc": completed_at.isoformat(),
        "results": completed_results,
        "rpc_totals": totals,
        "delta_cache_sha256": delta_sha,
        "report_file": str(report_path),
        "report_sha256": file_sha256(report_path),
    })
    write_json_atomic(state_path, _seal_state(state))

    summary = dict(report.get("summary") or {})
    print("M80_TARGETED_DEEP_QUALIFICATION=PASS")
    print("HELIUS_REQUESTS=0")
    print("HELIUS_CREDITS=0")
    print(f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('qualified_pending_short_canary', 0)}")
    print("QUALIFIED_WALLETS=" + ",".join(summary.get("qualified_wallets") or []))
    print("M74_MINIMUM_TWO_WALLETS_REACHED=" + ("YES" if summary.get("m74_minimum_wallet_count_reached") else "NO"))
    print(f"PUBLIC_RPC_REQUESTS_TOTAL={totals.get('requests', 0)}")
    print(f"PUBLIC_RPC_CACHE_HITS_TOTAL={totals.get('cache_hits', 0)}")
    print(f"PUBLIC_RPC_RETRY_429_TOTAL={totals.get('retry_429', 0)}")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print(f"NEXT={report.get('next_step')}")
    print(f"M80_REPORT_FILE={report_path}")
    print(f"M80_REPORT_SHA256={file_sha256(report_path)}")
    print(f"M80_DELTA_CACHE_FILE={delta_path}")
    print(f"M80_DELTA_CACHE_SHA256={delta_sha}")
    print(f"M80_STATE_FILE={state_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(f"M80_TARGETED_DEEP_QUALIFICATION=FAILED type={type(error).__name__} message={message}")
        raise SystemExit(1) from None
