from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_ALEMBIC_HEAD,
    M64_EXPECTED_DATABASE,
    canonical_sha256,
    file_sha256,
    readonly_database_url,
    write_json_atomic,
)
from backend.app.services.gen4_fast_discovery_qualification_service import (  # noqa: E402
    M81_CANDIDATE_HISTORIES_PER_LANE,
    M81_CONFIRMATION,
    M81_DISCOVERY_CREDIT_CAP_TOTAL,
    M81_DISCOVERY_REQUEST_CAP_TOTAL,
    M81_MAX_TRIAGE_CANDIDATES,
    M81_PASS1_SIGNATURES,
    M81_PASS2_SIGNATURES,
    M81_PASS2_WALLETS,
    M81_PASS3_SIGNATURES,
    M81_REQUIRED_QUALIFIED,
    M81_RPC_MAXIMUM_ATTEMPTS,
    M81_RPC_THROTTLE_SECONDS_PER_WORKER,
    M81_RPC_WORKERS,
    M81_SCOPE,
    M81_SEED_TOKENS_PER_LANE,
    M81_SEEDS,
    M81_VERSION,
    M81FastDiscoveryError,
    build_final_report,
    build_model_policy,
    build_result,
    merge_discovery_candidates,
    rank_results,
    select_pass2,
    select_pass3,
    stage_result_needs_retry,
    validate_final_report,
    validate_lineage,
)
from backend.app.services.gen4_controlled_helius_discovery_service import (  # noqa: E402
    M66_HELIUS_CONFIRMATION,
    build_helius_request_cache,
    execute_controlled_helius_discovery,
    validate_helius_request_cache,
)
from scripts.run_m67_m70_zero_helius_pre_micro_live import (  # noqa: E402
    CachedBudgetedPublicRpc,
    PublicRpcBudgetExhausted,
    _collect_deep_history,
    _finalize_cache,
    _signature_page,
)

EXPECTED_M66_REPORT_SHA256 = "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
EXPECTED_M79_REPORT_SHA256 = "ad717ae9a643ec5e9db8946e698416701b896a44ffd2844a4ab79801305f2bbf"
EXPECTED_M80_REPORT_SHA256 = "20c2d5d2bb8ee3c50fe2959edcdfe5b793fff1b2e0d4be73f8f2625fe8f13f44"
EXPECTED_M80_DELTA_CACHE_SHA256 = "5160da74bbd1a49ddee4a1e39f4b56f59d5463698377399c3969aec9c39cbb5e"
PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"
STATE_SCHEMA = "SMARTMONEY_M81_FAST_DISCOVERY_STATE_V1"
PUBLIC_CACHE_SCHEMA = "SMARTMONEY_M67_ZERO_HELIUS_PUBLIC_RPC_CACHE_V1"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="M81 fast controlled discovery + parallel Gen4 qualification.")
    p.add_argument("--confirmation", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--m66-report", required=True)
    p.add_argument("--m79-report", required=True)
    p.add_argument("--m80-report", required=True)
    p.add_argument("--m80-delta-cache", required=True)
    p.add_argument("--database-url-env", default="DATABASE_PUBLIC_URL")
    p.add_argument("--rpc-url", default=PUBLIC_RPC_URL)
    return p


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise M81FastDiscoveryError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M81FastDiscoveryError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M81FastDiscoveryError(f"Root {label} non oggetto.")
    return value


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = {k: v for k, v in state.items() if k != "integrity"}
    result = dict(payload)
    result["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return result


def _validate_state(state: dict[str, Any], input_hashes: dict[str, str]) -> dict[str, Any]:
    if state.get("schema") != STATE_SCHEMA:
        raise M81FastDiscoveryError("Schema state M81 inatteso.")
    payload = {k: v for k, v in state.items() if k != "integrity"}
    expected = str(dict(state.get("integrity") or {}).get("payload_sha256") or "")
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M81FastDiscoveryError("Hash state M81 non valido.")
    if dict(state.get("input_hashes") or {}) != input_hashes:
        raise M81FastDiscoveryError("Input M81 diversi dal resume state.")
    return state


def _empty_public_cache() -> dict[str, Any]:
    return _finalize_cache({"schema": PUBLIC_CACHE_SCHEMA, "public_origin": PUBLIC_RPC_URL, "entries": {}})


def _load_public_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _empty_public_cache()
    value = _load_json(path, "Cache RPC M81")
    if value.get("schema") != PUBLIC_CACHE_SCHEMA or value.get("public_origin") != PUBLIC_RPC_URL:
        raise M81FastDiscoveryError("Cache RPC M81 incompatibile.")
    expected = str(dict(value.get("integrity") or {}).get("payload_sha256") or "")
    payload = {k: v for k, v in value.items() if k != "integrity"}
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M81FastDiscoveryError("Hash cache RPC M81 non valido.")
    return value


def _merge_public_cache(global_cache: dict[str, Any], local_cache: dict[str, Any]) -> list[str]:
    entries = global_cache.setdefault("entries", {})
    added: list[str] = []
    for key, value in dict(local_cache.get("entries") or {}).items():
        if key in entries and entries[key] != value:
            raise M81FastDiscoveryError("Collisione cache RPC M81.")
        if key not in entries:
            entries[key] = value
            added.append(key)
    return sorted(set(dict(local_cache.get("entries") or {})))


def _subset_cache(global_cache: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    entries = dict(global_cache.get("entries") or {})
    subset = {key: entries[key] for key in keys if key in entries}
    return _finalize_cache({"schema": PUBLIC_CACHE_SCHEMA, "public_origin": PUBLIC_RPC_URL, "entries": subset})


def _write_public_cache(path: Path, cache: dict[str, Any]) -> str:
    finalized = _finalize_cache({"schema": cache.get("schema"), "public_origin": cache.get("public_origin"), "entries": dict(cache.get("entries") or {})})
    write_json_atomic(path, finalized)
    return file_sha256(path)


def _write_state(path: Path, state: dict[str, Any]) -> None:
    state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(path, _seal_state(state))


def _preflight_db(public_url: str) -> tuple[set[str], dict[str, Any]]:
    from backend.app.models.discovered_wallet import DiscoveredWallet  # noqa: WPS433
    from backend.app.services.helius_credit_guard_service import get_helius_credit_guard_status  # noqa: WPS433

    engine = create_engine(readonly_database_url(public_url), future=True, pool_pre_ping=True)
    connection = None
    transaction = None
    try:
        connection = engine.connect()
        transaction = connection.begin()
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        database_name = str(connection.execute(text("SELECT current_database()")).scalar_one())
        read_only = str(connection.execute(text("SHOW transaction_read_only")).scalar_one()).lower()
        alembic_head = str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        if database_name != M64_EXPECTED_DATABASE or read_only != "on" or alembic_head != M64_EXPECTED_ALEMBIC_HEAD:
            raise M81FastDiscoveryError("Preflight DB M81 non conforme.")
        with Session(bind=connection, autoflush=False, expire_on_commit=False) as db:
            cached = {str(v) for (v,) in db.query(DiscoveredWallet.wallet_address).all()}
            guard = dict(get_helius_credit_guard_status(db))
            if db.new or db.dirty or db.deleted:
                raise M81FastDiscoveryError("Preflight DB M81 ha mutato SQLAlchemy state.")
        return cached, guard
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()
        engine.dispose()


def _merge_helius_caches(caches: list[dict[str, Any]]) -> dict[str, Any]:
    histories: dict[str, list[dict[str, Any]]] = {}
    for cache in caches:
        for address, history in validate_helius_request_cache(cache).items():
            if address in histories and histories[address] != history:
                raise M81FastDiscoveryError("Collisione cache Helius M81.")
            histories[address] = history
    return build_helius_request_cache(histories)


def _worker(candidate: dict[str, Any], maximum_signatures: int, stage: str, seed_cache: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    request_cap = max(120, int(maximum_signatures * 1.30) + 25)
    rpc = CachedBudgetedPublicRpc(
        PUBLIC_RPC_URL,
        cache=seed_cache,
        request_cap=request_cap,
        maximum_attempts=M81_RPC_MAXIMUM_ATTEMPTS,
        throttle_seconds=M81_RPC_THROTTLE_SECONDS_PER_WORKER,
    )
    wallet = str(candidate["wallet_address"])
    try:
        policy = build_model_policy(maximum_signatures)
        first = _signature_page(rpc, wallet, limit=100)
        deep = _collect_deep_history(rpc, wallet, first_page=first, now=datetime.now(timezone.utc), policy=policy)
        if deep.get("public_rpc_budget_exhausted"):
            raise PublicRpcBudgetExhausted(f"Budget worker M81 esaurito: {wallet}")
        result = build_result(candidate, deep, stage=stage, maximum_signatures=maximum_signatures)
    except Exception as error:  # noqa: BLE001
        result = {
            "wallet_address": wallet,
            "stage": stage,
            "disposition": "RPC_RETRY_REQUIRED",
            "error_type": type(error).__name__,
            "error_message": " ".join(str(error).split())[:240],
            "prescreen_score": candidate.get("prescreen_score"),
            "short_canary_authorized": False,
            "micro_live_authorized": False,
        }
    finally:
        finalized_cache = _finalize_cache(rpc.cache)
        stats = rpc.stats()
        rpc.close()
    return result, finalized_cache, stats


def _run_parallel_stage(
    *,
    candidates: list[dict[str, Any]],
    maximum_signatures: int,
    stage: str,
    global_cache: dict[str, Any],
    wallet_cache_keys: dict[str, list[str]],
    state: dict[str, Any],
    state_path: Path,
    public_cache_path: Path,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    results: list[dict[str, Any]] = []
    totals = {"requests": 0, "cache_hits": 0, "retry_429": 0, "retry_5xx": 0, "retry_network": 0}
    with ThreadPoolExecutor(max_workers=M81_RPC_WORKERS, thread_name_prefix="m81-rpc") as pool:
        futures = {}
        for candidate in candidates:
            wallet = str(candidate["wallet_address"])
            seed = _subset_cache(global_cache, list(wallet_cache_keys.get(wallet) or []))
            future = pool.submit(_worker, candidate, maximum_signatures, stage, seed)
            futures[future] = candidate
        completed = 0
        for future in as_completed(futures):
            candidate = futures[future]
            wallet = str(candidate["wallet_address"])
            completed += 1
            try:
                result, local_cache, stats = future.result()
            except Exception as error:  # noqa: BLE001
                result = {
                    "wallet_address": wallet,
                    "stage": stage,
                    "disposition": "RPC_RETRY_REQUIRED",
                    "error_type": type(error).__name__,
                    "error_message": " ".join(str(error).split())[:240],
                    "prescreen_score": candidate.get("prescreen_score"),
                    "short_canary_authorized": False,
                    "micro_live_authorized": False,
                }
                local_cache = _empty_public_cache()
                stats = {}
            keys = _merge_public_cache(global_cache, local_cache)
            wallet_cache_keys[wallet] = sorted(set(list(wallet_cache_keys.get(wallet) or []) + keys))
            for key in totals:
                totals[key] += int(stats.get(key) or 0)
            results.append(result)
            state.setdefault("stage_results", {}).setdefault(stage, {})[wallet] = result
            state["wallet_cache_keys"] = wallet_cache_keys
            _write_public_cache(public_cache_path, global_cache)
            _write_state(state_path, state)
            if result.get("disposition") == "RPC_RETRY_REQUIRED":
                print(f"M81_{stage}_DONE={wallet};status=RPC_RETRY_REQUIRED", flush=True)
            else:
                print(
                    f"M81_{stage}_DONE={wallet};closed={result.get('closed_trade_count',0)};pf={result.get('profit_factor',0)};net={result.get('net_pnl_sol',0)};dd={result.get('maximum_drawdown_percent',0)};disp={result.get('disposition')}",
                    flush=True,
                )
            print(f"M81_{stage}_PROGRESS={completed}/{len(candidates)}", flush=True)
    return results, totals


def _latest_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    stages = dict(state.get("stage_results") or {})
    wallets: dict[str, dict[str, Any]] = {}
    for stage in ("PASS1", "PASS2", "PASS3"):
        for wallet, row in dict(stages.get(stage) or {}).items():
            wallets[str(wallet)] = dict(row)
    return list(wallets.values())


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M81_CONFIRMATION:
        raise M81FastDiscoveryError(f"Conferma richiesta: {M81_CONFIRMATION}.")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M81FastDiscoveryError("Output M81 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)

    parsed = urlsplit(str(args.rpc_url or ""))
    if parsed.scheme.lower() != "https" or str(parsed.hostname or "").lower() != "api.mainnet-beta.solana.com" or parsed.query or parsed.username or parsed.password:
        raise M81FastDiscoveryError("M81 parallel RPC usa solo endpoint pubblico Solana ufficiale senza credenziali.")

    input_paths = {
        "m66": Path(args.m66_report).expanduser().resolve(),
        "m79": Path(args.m79_report).expanduser().resolve(),
        "m80": Path(args.m80_report).expanduser().resolve(),
        "m80_cache": Path(args.m80_delta_cache).expanduser().resolve(),
    }
    input_hashes = {key: file_sha256(path) if path.is_file() else "" for key, path in input_paths.items()}
    expected = {
        "m66": EXPECTED_M66_REPORT_SHA256,
        "m79": EXPECTED_M79_REPORT_SHA256,
        "m80": EXPECTED_M80_REPORT_SHA256,
        "m80_cache": EXPECTED_M80_DELTA_CACHE_SHA256,
    }
    if input_hashes != expected:
        raise M81FastDiscoveryError("SHA lineage M66/M79/M80 inatteso.")
    old_m66 = _load_json(input_paths["m66"], "M66 report")
    m79 = _load_json(input_paths["m79"], "M79 report")
    m80 = _load_json(input_paths["m80"], "M80 report")
    excluded_lineage = validate_lineage(old_m66, m79, m80)

    suffix = EXPECTED_M80_REPORT_SHA256[:16]
    state_path = output_dir / f"smartmoney-m81-fast-discovery-state-{suffix}.json"
    public_cache_path = output_dir / f"smartmoney-m81-public-rpc-cache-{suffix}.json"
    helius_cache_path = output_dir / f"smartmoney-m81-helius-cache-{suffix}.json"
    print(f"M81_STATE_FILE={state_path}")
    print(f"M81_PUBLIC_RPC_CACHE_FILE={public_cache_path}")
    print(f"M81_HELIUS_CACHE_FILE={helius_cache_path}")

    if state_path.is_file():
        state = _validate_state(_load_json(state_path, "M81 state"), input_hashes)
        if state.get("status") == "COMPLETED":
            report_path = Path(str(state.get("report_file") or ""))
            if report_path.is_file():
                print("M81_FAST_DISCOVERY_QUALIFICATION=ALREADY_COMPLETED")
                print(f"M81_REPORT_FILE={report_path}")
                print(f"M81_REPORT_SHA256={file_sha256(report_path)}")
                return 0
        started = datetime.fromisoformat(str(state["started_at_utc"]).replace("Z", "+00:00"))
    else:
        started = datetime.now(timezone.utc)
        state = {
            "schema": STATE_SCHEMA,
            "version": M81_VERSION,
            "scope": M81_SCOPE,
            "status": "RUNNING",
            "started_at_utc": started.isoformat(),
            "updated_at_utc": started.isoformat(),
            "input_hashes": input_hashes,
            "discovery_lanes": [],
            "discovery_inflight": None,
            "discovery_candidates": [],
            "stage_results": {},
            "wallet_cache_keys": {},
            "public_rpc_totals": {"requests": 0, "cache_hits": 0, "retry_429": 0, "retry_5xx": 0, "retry_network": 0},
            "report_file": None,
        }
        _write_state(state_path, state)

    public_cache = _load_public_cache(public_cache_path)
    wallet_cache_keys = {str(k): list(v) for k, v in dict(state.get("wallet_cache_keys") or {}).items()}

    print("=== M81 FAST DISCOVERY + PARALLEL ECONOMIC QUALIFICATION ===")
    print(f"HELIUS_DISCOVERY_REQUEST_CAP={M81_DISCOVERY_REQUEST_CAP_TOTAL}")
    print(f"HELIUS_DISCOVERY_CREDIT_CAP={M81_DISCOVERY_CREDIT_CAP_TOTAL}")
    print(f"PARALLEL_RPC_WORKERS={M81_RPC_WORKERS}")
    print(f"RPC_THROTTLE_SECONDS_PER_WORKER={M81_RPC_THROTTLE_SECONDS_PER_WORKER}")
    print(f"EARLY_STOP_QUALIFIED_WALLETS={M81_REQUIRED_QUALIFIED}")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")

    # Discovery is one-shot per lane and checkpointed before economic RPC begins.
    lanes = list(state.get("discovery_lanes") or [])
    if len(lanes) < len(M81_SEEDS):
        env_name = str(args.database_url_env or "").strip()
        public_url = str(os.getenv(env_name) or "").strip()
        if not public_url:
            raise M81FastDiscoveryError(f"Variabile {env_name} assente.")
        os.environ["DATABASE_URL"] = public_url
        cached_db, guard = _preflight_db(public_url)
        remaining_lane_cap = (len(M81_SEEDS) - len(lanes)) * (M81_DISCOVERY_CREDIT_CAP_TOTAL // len(M81_SEEDS))
        if int(guard.get("daily_total_credits_remaining") or 0) < remaining_lane_cap:
            raise M81FastDiscoveryError(f"Budget totale Helius residuo < {remaining_lane_cap} richiesti per le lane restanti.")
        if int(guard.get("daily_enhanced_credits_remaining") or 0) < remaining_lane_cap:
            raise M81FastDiscoveryError(f"Budget Enhanced Helius residuo < {remaining_lane_cap} richiesti per le lane restanti.")
        from backend.app.core.config import settings  # noqa: WPS433
        key = str(getattr(settings, "HELIUS_API_KEY", "") or "").strip()
        if not key or key.upper() in {"CHANGE_ME", "CHANGEME", "TEST"}:
            raise M81FastDiscoveryError("HELIUS_API_KEY assente/placeholder.")

        existing_cache = None
        if helius_cache_path.is_file():
            existing_cache = _load_json(helius_cache_path, "M81 Helius cache")
        known = set(cached_db) | set(excluded_lineage)
        for lane in lanes:
            for wallet in lane.get("candidate_wallets") or []:
                known.add(str(wallet))

        inflight = state.get("discovery_inflight")
        if inflight:
            raise M81FastDiscoveryError("Lane Helius M81 precedente risulta STARTED ma non COMPLETED: fail-closed, non autorizzo re-spend automatico.")
        for lane_index in range(len(lanes), len(M81_SEEDS)):
            seed = M81_SEEDS[lane_index]
            state["discovery_inflight"] = {"lane": lane_index + 1, "seed_wallet": seed, "started_at_utc": datetime.now(timezone.utc).isoformat()}
            _write_state(state_path, state)
            print(f"M81_DISCOVERY_LANE_START={lane_index+1}/2;seed={seed}", flush=True)
            report, cache = execute_controlled_helius_discovery(
                confirmation=M66_HELIUS_CONFIRMATION,
                seed_wallet=seed,
                cached_wallet_addresses=known,
                maximum_seed_tokens=M81_SEED_TOKENS_PER_LANE,
                maximum_candidate_wallets=M81_CANDIDATE_HISTORIES_PER_LANE,
                request_cache=existing_cache,
            )
            lane_report_path = output_dir / f"smartmoney-m81-discovery-lane-{lane_index+1}-{suffix}.json"
            write_json_atomic(lane_report_path, report)
            existing_cache = _merge_helius_caches([cache])
            write_json_atomic(helius_cache_path, existing_cache)
            candidate_wallets = [str(r.get("wallet_address")) for r in report.get("candidate_results") or [] if isinstance(r, dict) and r.get("wallet_address")]
            known.update(candidate_wallets)
            lane_state = {
                "lane": lane_index + 1,
                "seed_wallet": seed,
                "report_file": str(lane_report_path),
                "report_sha256": file_sha256(lane_report_path),
                "cache_sha256": file_sha256(helius_cache_path),
                "requests": int(dict(report.get("budget") or {}).get("enhanced_requests_executed") or 0),
                "credits_reserved_maximum": int(dict(report.get("budget") or {}).get("enhanced_credits_reserved_maximum") or 0),
                "candidate_wallets": candidate_wallets,
            }
            lanes.append(lane_state)
            state["discovery_lanes"] = lanes
            state["discovery_inflight"] = None
            _write_state(state_path, state)
            print(f"M81_DISCOVERY_LANE_DONE={lane_index+1};requests={lane_state['requests']};candidates={len(candidate_wallets)}", flush=True)

    lane_reports = [_load_json(Path(str(lane["report_file"])), f"M81 lane {lane['lane']}") for lane in lanes]
    candidates = merge_discovery_candidates(lane_reports, excluded_lineage)
    state["discovery_candidates"] = candidates
    _write_state(state_path, state)
    print(f"M81_NEW_PRESCREEN_PASS_CANDIDATES={len(candidates)}")
    if not candidates:
        print("M81_NO_NEW_PRESCREEN_PASS=YES")

    by_wallet = {str(c["wallet_address"]): c for c in candidates}
    totals = dict(state.get("public_rpc_totals") or {})

    # PASS1: fast economic sample over all selected new candidates.
    existing_p1 = dict(dict(state.get("stage_results") or {}).get("PASS1") or {})
    pending1 = [
        c
        for c in candidates
        if str(c["wallet_address"]) not in existing_p1
        or stage_result_needs_retry(existing_p1.get(str(c["wallet_address"])))
    ]
    if pending1:
        print(f"M81_PASS1_START={len(pending1)};signatures={M81_PASS1_SIGNATURES}")
        rows, stage_stats = _run_parallel_stage(candidates=pending1, maximum_signatures=M81_PASS1_SIGNATURES, stage="PASS1", global_cache=public_cache, wallet_cache_keys=wallet_cache_keys, state=state, state_path=state_path, public_cache_path=public_cache_path)
        for key, value in stage_stats.items(): totals[key] = int(totals.get(key) or 0) + int(value)
        state["public_rpc_totals"] = totals
        _write_state(state_path, state)

    pass1_rows = list(dict(dict(state.get("stage_results") or {}).get("PASS1") or {}).values())
    latest = _latest_results(state)
    qualified = [r for r in latest if r.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"]
    early_stop = len(qualified) >= M81_REQUIRED_QUALIFIED
    if early_stop:
        print("M81_EARLY_STOP_TWO_M74_PASSES=YES", flush=True)
    else:
        pass2_wallets = select_pass2(pass1_rows)
        print("M81_PASS2_SELECTED=" + ",".join(pass2_wallets))
        existing_p2 = dict(dict(state.get("stage_results") or {}).get("PASS2") or {})
        pending2 = [
            by_wallet[w]
            for w in pass2_wallets
            if w in by_wallet
            and (w not in existing_p2 or stage_result_needs_retry(existing_p2.get(w)))
        ]
        if pending2:
            rows, stage_stats = _run_parallel_stage(candidates=pending2, maximum_signatures=M81_PASS2_SIGNATURES, stage="PASS2", global_cache=public_cache, wallet_cache_keys=wallet_cache_keys, state=state, state_path=state_path, public_cache_path=public_cache_path)
            for key, value in stage_stats.items(): totals[key] = int(totals.get(key) or 0) + int(value)
            state["public_rpc_totals"] = totals
            _write_state(state_path, state)

        latest = _latest_results(state)
        qualified = [r for r in latest if r.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"]
        early_stop = len(qualified) >= M81_REQUIRED_QUALIFIED

    if not early_stop:
        existing_p3 = dict(dict(state.get("stage_results") or {}).get("PASS3") or {})
        pass3_wallets = select_pass3(latest)
        for wallet, row in existing_p3.items():
            if stage_result_needs_retry(row) and wallet not in pass3_wallets:
                pass3_wallets.append(wallet)
        print("M81_PASS3_SELECTED=" + ",".join(pass3_wallets))
        # Two-at-a-time lets us stop without launching every expensive deep extension.
        remaining = [
            w
            for w in pass3_wallets
            if w in by_wallet
            and (w not in existing_p3 or stage_result_needs_retry(existing_p3.get(w)))
        ]
        for offset in range(0, len(remaining), 2):
            batch_wallets = remaining[offset:offset+2]
            batch = [by_wallet[w] for w in batch_wallets]
            if not batch:
                continue
            rows, stage_stats = _run_parallel_stage(candidates=batch, maximum_signatures=M81_PASS3_SIGNATURES, stage="PASS3", global_cache=public_cache, wallet_cache_keys=wallet_cache_keys, state=state, state_path=state_path, public_cache_path=public_cache_path)
            for key, value in stage_stats.items(): totals[key] = int(totals.get(key) or 0) + int(value)
            state["public_rpc_totals"] = totals
            _write_state(state_path, state)
            latest = _latest_results(state)
            qualified = [r for r in latest if r.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"]
            if len(qualified) >= M81_REQUIRED_QUALIFIED:
                early_stop = True
                print("M81_EARLY_STOP_TWO_M74_PASSES=YES", flush=True)
                break

    latest = _latest_results(state)
    discovery_requests = sum(int(lane.get("requests") or 0) for lane in lanes)
    discovery_credits = sum(int(lane.get("credits_reserved_maximum") or 0) for lane in lanes)
    if discovery_requests > M81_DISCOVERY_REQUEST_CAP_TOTAL or discovery_credits > M81_DISCOVERY_CREDIT_CAP_TOTAL:
        raise M81FastDiscoveryError("Budget Helius aggregato M81 oltre hard cap.")
    public_sha = _write_public_cache(public_cache_path, public_cache)
    completed = datetime.now(timezone.utc)
    report = build_final_report(
        input_hashes=input_hashes,
        started_at_utc=started.isoformat(),
        completed_at_utc=completed.isoformat(),
        discovery_lanes=lanes,
        discovery_requests=discovery_requests,
        discovery_credit_reserved_maximum=discovery_credits,
        candidates=candidates,
        final_results=latest,
        public_rpc_stats=totals,
        public_cache_sha256=public_sha,
        early_stop=early_stop,
    )
    validate_final_report(report)
    report_path = output_dir / ("smartmoney-m81-fast-discovery-qualification-" + completed.strftime("%Y%m%dT%H%M%SZ") + ".json")
    write_json_atomic(report_path, report)
    summary = dict(report.get("summary") or {})
    retry_required = (
        int(summary.get("qualified_pending_short_canary") or 0) < M81_REQUIRED_QUALIFIED
        and int(summary.get("rpc_retry_required") or 0) > 0
    )
    state["status"] = "RPC_RETRY_REQUIRED" if retry_required else "COMPLETED"
    state["report_file"] = str(report_path)
    state["report_sha256"] = file_sha256(report_path)
    _write_state(state_path, state)

    print("M81_FAST_DISCOVERY_QUALIFICATION=" + ("PARTIAL_RPC_RETRY_REQUIRED" if retry_required else "PASS"))
    print(f"HELIUS_REQUESTS={discovery_requests}")
    print(f"HELIUS_CREDITS_RESERVED_MAXIMUM={discovery_credits}")
    print(f"NEW_CANDIDATES_TRIAGED={len(candidates)}")
    print(f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('qualified_pending_short_canary',0)}")
    print("QUALIFIED_WALLETS=" + ",".join(summary.get("qualified_wallets") or []))
    print(f"RPC_RETRY_REQUIRED={summary.get('rpc_retry_required',0)}")
    print("RPC_RETRY_WALLETS=" + ",".join(summary.get("rpc_retry_wallets") or []))
    if retry_required:
        print("HELIUS_RESPEND_ON_RERUN=NO")
    print("M74_MINIMUM_TWO_WALLETS_REACHED=" + ("YES" if summary.get("m74_minimum_two_wallets_reached") else "NO"))
    print(f"PUBLIC_RPC_REQUESTS_TOTAL={int(totals.get('requests') or 0)}")
    print(f"PUBLIC_RPC_CACHE_HITS_TOTAL={int(totals.get('cache_hits') or 0)}")
    print(f"PUBLIC_RPC_RETRY_429_TOTAL={int(totals.get('retry_429') or 0)}")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print(f"NEXT={report.get('next_step')}")
    print(f"M81_REPORT_FILE={report_path}")
    print(f"M81_REPORT_SHA256={file_sha256(report_path)}")
    print(f"M81_PUBLIC_RPC_CACHE_FILE={public_cache_path}")
    print(f"M81_PUBLIC_RPC_CACHE_SHA256={public_sha}")
    print(f"M81_HELIUS_CACHE_FILE={helius_cache_path}")
    print(f"M81_HELIUS_CACHE_SHA256={file_sha256(helius_cache_path) if helius_cache_path.is_file() else ''}")
    print(f"M81_STATE_FILE={state_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"M81_FAST_DISCOVERY_QUALIFICATION=FAILED type={type(error).__name__} message={' '.join(str(error).split())}")
        raise SystemExit(1) from None
