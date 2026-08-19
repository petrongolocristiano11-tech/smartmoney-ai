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
from backend.app.services.gen4_paid_candidate_economic_triage_service import (  # noqa: E402
    M79_CONFIRMATION,
    M79_EXPECTED_REMAINING,
    M79_PASS1_SIGNATURES,
    M79_PASS2_SIGNATURES,
    M79_PASS2_WALLETS,
    M79_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
    M79_PUBLIC_RPC_REQUEST_CAP,
    M79_PUBLIC_RPC_THROTTLE_SECONDS,
    M79_SCOPE,
    M79_VERSION,
    M79EconomicTriageError,
    build_final_report,
    build_model_policy,
    build_triage_result,
    extract_paid_remaining_candidates,
    rank_results,
    select_pass2_wallets,
    validate_final_report,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import (  # noqa: E402
    CachedBudgetedPublicRpc,
    PublicRpcBudgetExhausted,
    _collect_deep_history,
    _finalize_cache,
    _load_cache,
    _signature_page,
)


EXPECTED_M66_REPORT_SHA256 = "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
EXPECTED_M73_REPORT_SHA256 = "adf92b8b58fd683705bf8adfff1d8ae0bd5b90ae3c6626e61103f671a7132fea"
EXPECTED_M73_BASE_CACHE_SHA256 = "c4f3b4e0669363d90eb9c4f31c3725d476eeec6a84504867fd02a3e724740608"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
STATE_SCHEMA = "SMARTMONEY_M79_PAID_CANDIDATE_TRIAGE_STATE_V1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M79: riusa i 21 candidati M66 gia pagati e li ordina con un triage "
            "economico Gen4 adattivo via solo RPC pubblico Solana. Zero Helius."
        )
    )
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--m66-report", required=True)
    parser.add_argument("--m73-report", required=True)
    parser.add_argument("--m73-base-cache", required=True)
    parser.add_argument("--rpc-url", default=PUBLIC_RPC_URL)
    return parser


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise M79EconomicTriageError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M79EconomicTriageError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M79EconomicTriageError(f"Root {label} non oggetto.")
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


def _validate_state(state: dict[str, Any], *, input_hashes: dict[str, str]) -> dict[str, Any]:
    if state.get("schema") != STATE_SCHEMA:
        raise M79EconomicTriageError("Schema stato M79 inatteso.")
    expected = str(dict(state.get("integrity") or {}).get("payload_sha256") or "")
    payload = _state_payload(state)
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M79EconomicTriageError("Hash stato M79 non valido.")
    if dict(state.get("input_hashes") or {}) != input_hashes:
        raise M79EconomicTriageError("Input M79 diversi dallo stato di resume.")
    return state


def _empty_delta_cache(public_origin: str) -> dict[str, Any]:
    return _finalize_cache(
        {
            "schema": "SMARTMONEY_M67_ZERO_HELIUS_PUBLIC_RPC_CACHE_V1",
            "public_origin": public_origin,
            "entries": {},
        }
    )


def _merge_caches(
    base_cache: dict[str, Any],
    delta_cache: dict[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    base_entries = dict(base_cache.get("entries") or {})
    delta_entries = dict(delta_cache.get("entries") or {})
    overlap = set(base_entries).intersection(delta_entries)
    for key in overlap:
        if base_entries[key] != delta_entries[key]:
            raise M79EconomicTriageError("Collisione tra cache base M73 e delta M79.")
    merged = {
        "schema": base_cache.get("schema"),
        "public_origin": base_cache.get("public_origin"),
        "entries": {**base_entries, **delta_entries},
    }
    return merged, set(base_entries)


def _write_delta_cache(
    *,
    merged_cache: dict[str, Any],
    base_keys: set[str],
    delta_path: Path,
) -> str:
    delta = {
        "schema": merged_cache.get("schema"),
        "public_origin": merged_cache.get("public_origin"),
        "entries": {
            key: value
            for key, value in dict(merged_cache.get("entries") or {}).items()
            if key not in base_keys
        },
    }
    finalized = _finalize_cache(delta)
    write_json_atomic(delta_path, finalized)
    return file_sha256(delta_path)


def _rpc_totals(base: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    additive = ("requests", "cache_hits", "retry_429", "retry_5xx", "retry_network")
    result = {
        "public_origin": current.get("public_origin"),
        "request_cap_per_process": M79_PUBLIC_RPC_REQUEST_CAP,
        "maximum_attempts": M79_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
        "throttle_seconds": M79_PUBLIC_RPC_THROTTLE_SECONDS,
        "helius_requests": 0,
    }
    for key in additive:
        result[key] = int(base.get(key) or 0) + int(current.get(key) or 0)
    return result


def _checkpoint(
    *,
    state: dict[str, Any],
    state_path: Path,
    merged_cache: dict[str, Any],
    base_keys: set[str],
    delta_path: Path,
    process_base_rpc_totals: dict[str, Any],
    rpc: CachedBudgetedPublicRpc,
) -> None:
    delta_sha = _write_delta_cache(
        merged_cache=merged_cache,
        base_keys=base_keys,
        delta_path=delta_path,
    )
    state["delta_cache_sha256"] = delta_sha
    state["rpc_totals"] = _rpc_totals(process_base_rpc_totals, rpc.stats())
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(state_path, _seal_state(state))


def _run_wallet(
    *,
    rpc: CachedBudgetedPublicRpc,
    candidate: dict[str, Any],
    maximum_signatures: int,
    pass_name: str,
    started: datetime,
) -> dict[str, Any]:
    policy = build_model_policy(maximum_signatures=maximum_signatures)
    wallet = str(candidate.get("wallet_address") or "")
    first_page = _signature_page(rpc, wallet, limit=100)
    deep = _collect_deep_history(
        rpc,
        wallet,
        first_page=first_page,
        now=started,
        policy=policy,
    )
    if deep.get("public_rpc_budget_exhausted"):
        raise PublicRpcBudgetExhausted(
            f"Cap RPC M79 raggiunto durante {pass_name} wallet={wallet}."
        )
    return build_triage_result(
        candidate,
        deep,
        pass_name=pass_name,
        policy=policy,
    )


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M79_CONFIRMATION:
        raise M79EconomicTriageError(f"Conferma richiesta: {M79_CONFIRMATION}.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M79EconomicTriageError("Output M79 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlsplit(str(args.rpc_url or "").strip())
    if (
        parsed.scheme.lower() != "https"
        or str(parsed.hostname or "").lower() != "api.mainnet-beta.solana.com"
        or parsed.query
        or parsed.username
        or parsed.password
    ):
        raise M79EconomicTriageError(
            "M79 accetta solo https://api.mainnet-beta.solana.com senza credenziali/query."
        )
    public_origin = "https://api.mainnet-beta.solana.com"

    m66_path = Path(args.m66_report).expanduser().resolve()
    m73_path = Path(args.m73_report).expanduser().resolve()
    base_cache_path = Path(args.m73_base_cache).expanduser().resolve()
    input_hashes = {
        "m66_report_sha256": file_sha256(m66_path) if m66_path.is_file() else "",
        "m73_report_sha256": file_sha256(m73_path) if m73_path.is_file() else "",
        "m73_base_cache_sha256": file_sha256(base_cache_path)
        if base_cache_path.is_file()
        else "",
    }
    if input_hashes["m66_report_sha256"] != EXPECTED_M66_REPORT_SHA256:
        raise M79EconomicTriageError("SHA report M66 inatteso.")
    if input_hashes["m73_report_sha256"] != EXPECTED_M73_REPORT_SHA256:
        raise M79EconomicTriageError("SHA report M73 inatteso.")
    if input_hashes["m73_base_cache_sha256"] != EXPECTED_M73_BASE_CACHE_SHA256:
        raise M79EconomicTriageError("SHA cache base M73 inatteso.")

    m66_report = _load_json(m66_path, label="Report M66")
    m73_report = _load_json(m73_path, label="Report M73")
    candidates = extract_paid_remaining_candidates(m66_report, m73_report)
    by_wallet = {str(item["wallet_address"]): item for item in candidates}

    suffix = EXPECTED_M73_REPORT_SHA256[:16]
    state_path = output_dir / f"smartmoney-m79-paid-candidate-triage-state-{suffix}.json"
    delta_path = output_dir / f"smartmoney-m79-public-rpc-delta-cache-{suffix}.json"
    print(f"M79_STATE_FILE={state_path}")
    print(f"M79_DELTA_CACHE_FILE={delta_path}")

    base_cache = _load_cache(str(base_cache_path), public_origin=public_origin)
    if delta_path.is_file():
        delta_cache = _load_cache(str(delta_path), public_origin=public_origin)
    else:
        delta_cache = _empty_delta_cache(public_origin)
    merged_cache, base_keys = _merge_caches(base_cache, delta_cache)

    if state_path.is_file():
        state = _validate_state(
            _load_json(state_path, label="Stato M79"), input_hashes=input_hashes
        )
        if state.get("status") == "COMPLETED":
            report_path_text = str(state.get("report_file") or "")
            report_path = Path(report_path_text) if report_path_text else Path()
            if report_path_text and report_path.is_file():
                print("M79_PAID_CANDIDATE_ZERO_HELIUS_TRIAGE=ALREADY_COMPLETED")
                print(f"M79_REPORT_FILE={report_path}")
                print(f"M79_REPORT_SHA256={file_sha256(report_path)}")
                print(f"M79_DELTA_CACHE_FILE={delta_path}")
                print(f"M79_DELTA_CACHE_SHA256={file_sha256(delta_path)}")
                print("HELIUS_REQUESTS=0")
                print("HELIUS_CREDITS=0")
                return 0
            raise M79EconomicTriageError("Stato M79 COMPLETED ma report assente.")
        started = datetime.fromisoformat(str(state["started_at_utc"]).replace("Z", "+00:00"))
    else:
        started = datetime.now(timezone.utc)
        state = {
            "schema": STATE_SCHEMA,
            "version": M79_VERSION,
            "scope": M79_SCOPE,
            "status": "RUNNING",
            "started_at_utc": started.isoformat(),
            "updated_at_utc": started.isoformat(),
            "input_hashes": input_hashes,
            "pass1_results": {},
            "pass2_selected": [],
            "pass2_results": {},
            "rpc_totals": {},
            "delta_cache_sha256": None,
            "report_file": None,
            "report_sha256": None,
        }

    process_base_rpc_totals = dict(state.get("rpc_totals") or {})
    rpc = CachedBudgetedPublicRpc(
        str(args.rpc_url),
        cache=merged_cache,
        request_cap=M79_PUBLIC_RPC_REQUEST_CAP,
        maximum_attempts=M79_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
        throttle_seconds=M79_PUBLIC_RPC_THROTTLE_SECONDS,
    )

    print("=== M79 PAID CANDIDATE ZERO-HELIUS ECONOMIC TRIAGE ===")
    print("M66_REEXECUTION=NO")
    print("HELIUS_REQUESTS_AUTHORIZED=0")
    print("HELIUS_CREDITS_AUTHORIZED=0")
    print(f"PAID_PRESCREEN_CANDIDATES_REMAINING={M79_EXPECTED_REMAINING}")
    print(f"PASS1_SIGNATURES_PER_WALLET={M79_PASS1_SIGNATURES}")
    print(f"PASS2_WALLETS={M79_PASS2_WALLETS}")
    print(f"PASS2_SIGNATURES_PER_WALLET={M79_PASS2_SIGNATURES}")
    print(f"PUBLIC_RPC_REQUEST_CAP_PER_PROCESS={M79_PUBLIC_RPC_REQUEST_CAP}")
    print(f"PUBLIC_RPC_THROTTLE_SECONDS={M79_PUBLIC_RPC_THROTTLE_SECONDS}")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")

    try:
        pass1_results = dict(state.get("pass1_results") or {})
        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                -float(item.get("prescreen_score") or 0.0),
                str(item.get("wallet_address") or ""),
            ),
        )
        for index, candidate in enumerate(ordered_candidates, start=1):
            wallet = str(candidate["wallet_address"])
            if wallet in pass1_results:
                continue
            print(f"M79_PASS1_WALLET_START={index}/{M79_EXPECTED_REMAINING}:{wallet}", flush=True)
            result = _run_wallet(
                rpc=rpc,
                candidate=candidate,
                maximum_signatures=M79_PASS1_SIGNATURES,
                pass_name="PASS1_60_SIGNATURE_TRIAGE",
                started=started,
            )
            pass1_results[wallet] = result
            state["pass1_results"] = pass1_results
            _checkpoint(
                state=state,
                state_path=state_path,
                merged_cache=merged_cache,
                base_keys=base_keys,
                delta_path=delta_path,
                process_base_rpc_totals=process_base_rpc_totals,
                rpc=rpc,
            )
            metrics = dict(result.get("metrics") or {})
            print(
                "M79_PASS1_WALLET_DONE="
                f"{wallet};tier={result.get('priority_tier')};"
                f"closed={metrics.get('closed_trade_count')};"
                f"pf={metrics.get('profit_factor')};"
                f"net={metrics.get('net_pnl_sol')}",
                flush=True,
            )

        if len(pass1_results) != M79_EXPECTED_REMAINING:
            raise M79EconomicTriageError("Pass1 M79 non ha completato i 21 wallet.")

        pass2_selected = list(state.get("pass2_selected") or [])
        if not pass2_selected:
            pass2_selected = select_pass2_wallets(list(pass1_results.values()))
            state["pass2_selected"] = pass2_selected
            _checkpoint(
                state=state,
                state_path=state_path,
                merged_cache=merged_cache,
                base_keys=base_keys,
                delta_path=delta_path,
                process_base_rpc_totals=process_base_rpc_totals,
                rpc=rpc,
            )
            print("M79_PASS2_SELECTED=" + ",".join(pass2_selected), flush=True)

        pass2_results = dict(state.get("pass2_results") or {})
        for index, wallet in enumerate(pass2_selected, start=1):
            if wallet in pass2_results:
                continue
            candidate = by_wallet.get(wallet)
            if candidate is None:
                raise M79EconomicTriageError("Wallet pass2 non appartiene ai 21 candidati.")
            print(f"M79_PASS2_WALLET_START={index}/{M79_PASS2_WALLETS}:{wallet}", flush=True)
            result = _run_wallet(
                rpc=rpc,
                candidate=candidate,
                maximum_signatures=M79_PASS2_SIGNATURES,
                pass_name="PASS2_150_SIGNATURE_ECONOMIC_TRIAGE",
                started=started,
            )
            pass2_results[wallet] = result
            state["pass2_results"] = pass2_results
            _checkpoint(
                state=state,
                state_path=state_path,
                merged_cache=merged_cache,
                base_keys=base_keys,
                delta_path=delta_path,
                process_base_rpc_totals=process_base_rpc_totals,
                rpc=rpc,
            )
            metrics = dict(result.get("metrics") or {})
            print(
                "M79_PASS2_WALLET_DONE="
                f"{wallet};tier={result.get('priority_tier')};"
                f"closed={metrics.get('closed_trade_count')};"
                f"pf={metrics.get('profit_factor')};"
                f"net={metrics.get('net_pnl_sol')};"
                f"dd={metrics.get('maximum_drawdown_percent')}",
                flush=True,
            )

        if len(pass2_results) != M79_PASS2_WALLETS:
            raise M79EconomicTriageError("Pass2 M79 non ha completato gli 8 wallet.")

        # Final cache/state checkpoint before sealing the report.
        _checkpoint(
            state=state,
            state_path=state_path,
            merged_cache=merged_cache,
            base_keys=base_keys,
            delta_path=delta_path,
            process_base_rpc_totals=process_base_rpc_totals,
            rpc=rpc,
        )
        delta_sha = file_sha256(delta_path)
        completed = datetime.now(timezone.utc)
        cumulative_stats = _rpc_totals(process_base_rpc_totals, rpc.stats())
        report = build_final_report(
            m66_report_sha256=input_hashes["m66_report_sha256"],
            m73_report_sha256=input_hashes["m73_report_sha256"],
            base_cache_sha256=input_hashes["m73_base_cache_sha256"],
            delta_cache_sha256=delta_sha,
            started_at_utc=started.isoformat(),
            completed_at_utc=completed.isoformat(),
            pass1_results=list(pass1_results.values()),
            pass2_results=list(pass2_results.values()),
            pass2_selected=pass2_selected,
            m73_report=m73_report,
            rpc_stats=cumulative_stats,
        )
        validate_final_report(report)
        stamp = completed.strftime("%Y%m%dT%H%M%SZ")
        report_path = output_dir / f"smartmoney-m79-paid-candidate-zero-helius-triage-{stamp}.json"
        write_json_atomic(report_path, report)

        state["status"] = "COMPLETED"
        state["completed_at_utc"] = completed.isoformat()
        state["report_file"] = str(report_path)
        state["report_sha256"] = file_sha256(report_path)
        state["rpc_totals"] = cumulative_stats
        state["delta_cache_sha256"] = delta_sha
        write_json_atomic(state_path, _seal_state(state))

        ranked = rank_results(list(pass2_results.values()))
        top = ranked[:6]
        print("M79_PAID_CANDIDATE_ZERO_HELIUS_TRIAGE=PASS")
        print("M66_REEXECUTION=NO")
        print("HELIUS_REQUESTS=0")
        print("HELIUS_CREDITS=0")
        print(f"PASS1_COMPLETED={len(pass1_results)}")
        print(f"PASS2_COMPLETED={len(pass2_results)}")
        print("M79_RECOMMENDED_NEXT_DEEP=" + ",".join(str(item["wallet_address"]) for item in top))
        for index, item in enumerate(top, start=1):
            metrics = dict(item.get("metrics") or {})
            recent = dict(item.get("recent_metrics") or {})
            print(
                f"M79_TOP_{index}="
                f"{item.get('wallet_address')};tier={item.get('priority_tier')};"
                f"closed={metrics.get('closed_trade_count')};pf={metrics.get('profit_factor')};"
                f"net={metrics.get('net_pnl_sol')};wr={metrics.get('win_rate_percent')};"
                f"dd={metrics.get('maximum_drawdown_percent')};recent_pf={recent.get('profit_factor')}"
            )
        print(f"PUBLIC_RPC_REQUESTS_TOTAL={cumulative_stats.get('requests', 0)}")
        print(f"PUBLIC_RPC_CACHE_HITS_TOTAL={cumulative_stats.get('cache_hits', 0)}")
        print(f"PUBLIC_RPC_RETRY_429_TOTAL={cumulative_stats.get('retry_429', 0)}")
        print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
        print("LIVE_ORDERS=0")
        print("SIGNER_AUTHORIZED=NO")
        print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
        print(f"M79_REPORT_FILE={report_path}")
        print(f"M79_REPORT_SHA256={file_sha256(report_path)}")
        print(f"M79_DELTA_CACHE_FILE={delta_path}")
        print(f"M79_DELTA_CACHE_SHA256={delta_sha}")
        print(f"M79_STATE_FILE={state_path}")
        return 0
    except Exception:
        # Preserve every completed RPC response before surfacing the failure.
        try:
            _checkpoint(
                state=state,
                state_path=state_path,
                merged_cache=merged_cache,
                base_keys=base_keys,
                delta_path=delta_path,
                process_base_rpc_totals=process_base_rpc_totals,
                rpc=rpc,
            )
        except Exception:
            pass
        raise
    finally:
        rpc.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M79_PAID_CANDIDATE_ZERO_HELIUS_TRIAGE=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        print("M66_REEXECUTION=NO")
        print("HELIUS_REQUESTS=0")
        print("HELIUS_CREDITS=0")
        print("AUTO_RETRY=NO")
        raise SystemExit(1) from None
