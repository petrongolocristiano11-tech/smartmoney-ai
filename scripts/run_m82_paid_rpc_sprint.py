from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import settings  # noqa: E402
from backend.app.database.session import SessionLocal  # noqa: E402
from backend.app.services.blockchain_parser_gen4_copyability_service import (  # noqa: E402
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)
from backend.app.services.gen4_m82_paid_rpc_sprint_service import (  # noqa: E402
    M82_CONFIRMATION,
    M82_DISCOVERY_TX_PER_TOKEN,
    M82_GTFA_CREDITS_PER_REQUEST,
    M82_HISTORY_LOOKBACK_DAYS,
    M82_MAXIMUM_ATTEMPTS,
    M82_MAX_RPC_CREDITS,
    M82_PASS1_CANDIDATES,
    M82_PASS1_TRANSACTIONS,
    M82_PASS2_TRANSACTIONS,
    M82_PASS3_TRANSACTIONS,
    M82_REQUIRED_QUALIFIED,
    M82_SCOPE,
    M82_VERSION,
    M82_WORKERS,
    M82PaidRpcSprintError,
    build_final_report,
    build_model_policy,
    build_result,
    discover_candidates,
    known_wallets,
    normalize_full_transaction,
    rank_results,
    select_discovery_tokens,
    select_pass2,
    select_pass3,
    validate_final_report,
    validate_inputs,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    simulate_gen4_from_public_events,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    parse_public_transactions,
)
from backend.app.services.helius_credit_guard_service import (  # noqa: E402
    CATEGORY_RPC,
    HeliusCreditGuardError,
    get_helius_credit_guard_status,
    reserve_helius_credits,
)

EXPECTED_M66_SHA256 = "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
EXPECTED_M79_SHA256 = "ad717ae9a643ec5e9db8946e698416701b896a44ffd2844a4ab79801305f2bbf"
EXPECTED_M80_SHA256 = "20c2d5d2bb8ee3c50fe2959edcdfe5b793fff1b2e0d4be73f8f2625fe8f13f44"
EXPECTED_M81_STATE_SHA256 = "472cbcde352e8ba1681f39aee765452b48692af1964bec1f293094526942016c"

STATE_SCHEMA = "SMARTMONEY_M82_PAID_RPC_SPRINT_STATE_V1"
CACHE_MANIFEST_SCHEMA = "SMARTMONEY_M82_GTFA_CACHE_MANIFEST_V1"
CACHE_ENTRY_SCHEMA = "SMARTMONEY_M82_GTFA_CACHE_ENTRY_V1"
HELIUS_RPC_ORIGIN = "https://mainnet.helius-rpc.com/"
EXPECTED_PARSER_VERSION = "canonical-parser-gen4-raw-balance-delta/4"
M82_RESUME_HOTFIX = "checkpoint-lock-policy-resume/1"
_STATE_LOCK = threading.RLock()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="M82 stablecoin-hardened Helius paid-RPC discovery and qualification sprint."
    )
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--m66-report", required=True)
    parser.add_argument("--m79-report", required=True)
    parser.add_argument("--m80-report", required=True)
    parser.add_argument("--m81-state", required=True)
    return parser


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise M82PaidRpcSprintError(f"{label} non trovato: {path.name}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M82PaidRpcSprintError(f"{label} non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M82PaidRpcSprintError(f"Root {label} non oggetto.")
    return value


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in state.items() if key != "integrity"}
    result = dict(payload)
    result["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return result


def _write_state(path: Path, state: dict[str, Any]) -> None:
    # All M82 threads share one checkpoint path.  Serializing every atomic
    # write prevents Windows from observing two writers competing for the
    # same ``.tmp`` file used by write_json_atomic().
    with _STATE_LOCK:
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        write_json_atomic(path, _seal_state(state))


def _cleanup_stale_state_tmp(path: Path) -> bool:
    temporary = path.with_suffix(path.suffix + ".tmp")
    if not temporary.exists():
        return False
    if not path.is_file():
        raise M82PaidRpcSprintError("M82_STALE_TMP_WITHOUT_STATE")
    try:
        current = path.read_bytes()
        stale = temporary.read_bytes()
    except OSError as error:
        raise M82PaidRpcSprintError("M82_STALE_TMP_UNREADABLE") from error
    if current != stale:
        raise M82PaidRpcSprintError("M82_STALE_TMP_DIFFERS_FROM_STATE")
    try:
        temporary.unlink()
    except OSError as error:
        raise M82PaidRpcSprintError("M82_STALE_TMP_REMOVE_FAILED") from error
    return True


def _repair_retry_rows_for_resume(path: Path, state: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    with _STATE_LOCK:
        stages = state.setdefault("stage_results", {})
        for stage in ("PASS1", "PASS2", "PASS3"):
            rows = stages.get(stage)
            if not isinstance(rows, dict):
                continue
            for wallet, row in list(rows.items()):
                if isinstance(row, dict) and row.get("disposition") == "RPC_RETRY_REQUIRED":
                    removed.append(f"{stage}:{wallet}")
                    del rows[wallet]
        if removed:
            hotfixes = list(state.get("runtime_hotfixes") or [])
            if M82_RESUME_HOTFIX not in hotfixes:
                hotfixes.append(M82_RESUME_HOTFIX)
            state["runtime_hotfixes"] = hotfixes
            state["stage_completed"] = 0
            _write_state(path, state)
    return removed


def _validate_state(
    state: dict[str, Any],
    *,
    input_hashes: dict[str, str],
) -> dict[str, Any]:
    if state.get("schema") != STATE_SCHEMA:
        raise M82PaidRpcSprintError("Schema state M82 inatteso.")
    payload = {key: value for key, value in state.items() if key != "integrity"}
    expected = str(dict(state.get("integrity") or {}).get("payload_sha256") or "")
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M82PaidRpcSprintError("Hash state M82 non valido.")
    if dict(state.get("input_hashes") or {}) != input_hashes:
        raise M82PaidRpcSprintError("Input M82 diversi dal resume state.")
    return state


def _safe_rpc_endpoint(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _normalize_gtfa_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M82PaidRpcSprintError("Risposta getTransactionsForAddress non oggetto.")
    data = value.get("data")
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise M82PaidRpcSprintError("Risposta getTransactionsForAddress.data non valida.")
    token = value.get("paginationToken")
    if token is not None and not isinstance(token, str):
        raise M82PaidRpcSprintError("paginationToken Helius non valido.")
    return {"data": [dict(item) for item in data], "paginationToken": token}


class CachedGuardedGtfaClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        state: dict[str, Any],
        state_path: Path,
        effective_total_credit_cap: int,
    ):
        self.cache_dir = cache_dir
        self.entries_dir = cache_dir / "entries"
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.state = state
        self.state_path = state_path
        self.effective_total_credit_cap = int(effective_total_credit_cap)
        self.lock = threading.RLock()
        self.inflight: dict[str, threading.Event] = {}
        self.network_successes = 0
        self.cache_hits = 0
        self.retry_429 = 0
        self.retry_5xx = 0
        self.retry_network = 0
        self.safe_endpoint = _safe_rpc_endpoint(HELIUS_RPC_ORIGIN)

    def _request_contract(self, address: str, config: dict[str, Any]) -> dict[str, Any]:
        return {
            "method": "getTransactionsForAddress",
            "address": str(address),
            "config": dict(config),
            "rpc_origin": self.safe_endpoint,
            "credits_per_attempt": M82_GTFA_CREDITS_PER_REQUEST,
        }

    def _entry_path(self, key: str) -> Path:
        return self.entries_dir / f"{key}.json"

    def _read_entry(self, path: Path, contract: dict[str, Any]) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        value = _load_json(path, "Cache entry M82")
        if value.get("schema") != CACHE_ENTRY_SCHEMA:
            raise M82PaidRpcSprintError("Schema cache entry M82 inatteso.")
        if dict(value.get("request") or {}) != contract:
            raise M82PaidRpcSprintError("Contratto cache entry M82 diverso.")
        expected = str(value.get("result_sha256") or "")
        result = value.get("result")
        if len(expected) != 64 or expected != canonical_sha256(result):
            raise M82PaidRpcSprintError("Hash result cache entry M82 non valido.")
        return _normalize_gtfa_result(result)

    def _reserve_attempt(self, origin: str) -> None:
        with self.lock:
            current = int(self.state.get("credits_reserved") or 0)
            if current + M82_GTFA_CREDITS_PER_REQUEST > self.effective_total_credit_cap:
                raise M82PaidRpcSprintError(
                    "M82_CREDIT_CAP_REACHED_BEFORE_NETWORK_REQUEST"
                )
            try:
                reserve_helius_credits(
                    category=CATEGORY_RPC,
                    estimated_credits=M82_GTFA_CREDITS_PER_REQUEST,
                    origin=origin[:120],
                    automatic=False,
                )
            except HeliusCreditGuardError as error:
                raise M82PaidRpcSprintError(
                    f"HELIUS_CREDIT_GUARD_BLOCKED:{error.code}"
                ) from None
            with _STATE_LOCK:
                self.state["credits_reserved"] = (
                    current + M82_GTFA_CREDITS_PER_REQUEST
                )
                self.state["network_attempts_reserved"] = int(
                    self.state.get("network_attempts_reserved") or 0
                ) + 1
                _write_state(self.state_path, self.state)

    def call(self, address: str, config: dict[str, Any], *, origin: str) -> dict[str, Any]:
        contract = self._request_contract(address, config)
        key = canonical_sha256(contract)
        path = self._entry_path(key)

        while True:
            with self.lock:
                cached = self._read_entry(path, contract)
                if cached is not None:
                    self.cache_hits += 1
                    return cached
                event = self.inflight.get(key)
                if event is None:
                    event = threading.Event()
                    self.inflight[key] = event
                    owner = True
                else:
                    owner = False
            if owner:
                break
            event.wait(timeout=60)

        last_error: Exception | None = None
        try:
            for attempt in range(1, M82_MAXIMUM_ATTEMPTS + 1):
                self._reserve_attempt(origin)
                response: httpx.Response | None = None
                try:
                    response = httpx.post(
                        HELIUS_RPC_ORIGIN,
                        params={"api-key": settings.HELIUS_API_KEY},
                        json={
                            "jsonrpc": "2.0",
                            "id": "m82",
                            "method": "getTransactionsForAddress",
                            "params": [address, config],
                        },
                        timeout=float(
                            getattr(settings, "HELIUS_REQUEST_TIMEOUT_SECONDS", 20.0)
                        ),
                    )
                    if response.status_code == 429:
                        with self.lock:
                            self.retry_429 += 1
                        last_error = M82PaidRpcSprintError("HELIUS_HTTP_429")
                    elif response.status_code in {500, 502, 503, 504}:
                        with self.lock:
                            self.retry_5xx += 1
                        last_error = M82PaidRpcSprintError(
                            f"HELIUS_HTTP_{response.status_code}"
                        )
                    elif response.status_code >= 400:
                        raise M82PaidRpcSprintError(
                            f"HELIUS_HTTP_NON_RETRYABLE_{response.status_code}"
                        )
                    else:
                        body = response.json()
                        if not isinstance(body, dict):
                            raise M82PaidRpcSprintError("HELIUS_JSON_ROOT_INVALID")
                        if body.get("error"):
                            error = body.get("error")
                            code = error.get("code") if isinstance(error, dict) else "UNKNOWN"
                            raise M82PaidRpcSprintError(f"HELIUS_RPC_ERROR_{code}")
                        result = _normalize_gtfa_result(body.get("result"))
                        entry = {
                            "schema": CACHE_ENTRY_SCHEMA,
                            "request": contract,
                            "result": result,
                            "result_sha256": canonical_sha256(result),
                        }
                        write_json_atomic(path, entry)
                        with self.lock:
                            self.network_successes += 1
                        return result
                except (httpx.RequestError, ValueError) as error:
                    with self.lock:
                        self.retry_network += 1
                    last_error = error

                if attempt < M82_MAXIMUM_ATTEMPTS:
                    retry_after = None
                    if response is not None:
                        retry_after = response.headers.get("retry-after")
                    try:
                        delay = max(0.25, min(float(retry_after), 3.0)) if retry_after else min(0.5 * attempt, 2.0)
                    except (TypeError, ValueError):
                        delay = min(0.5 * attempt, 2.0)
                    time.sleep(delay)

            raise M82PaidRpcSprintError(
                f"HELIUS_GTFA_RETRY_EXHAUSTED:{type(last_error).__name__}"
            )
        finally:
            with self.lock:
                event = self.inflight.pop(key, None)
                if event is not None:
                    event.set()

    def stats(self) -> dict[str, Any]:
        with self.lock:
            return {
                "successful_network_requests_current_process": self.network_successes,
                "cache_hits_current_process": self.cache_hits,
                "retry_429_current_process": self.retry_429,
                "retry_5xx_current_process": self.retry_5xx,
                "retry_network_current_process": self.retry_network,
                "credits_reserved": int(self.state.get("credits_reserved") or 0),
                "network_attempts_reserved": int(
                    self.state.get("network_attempts_reserved") or 0
                ),
            }

    def write_manifest(self) -> tuple[Path, str]:
        rows: list[dict[str, Any]] = []
        for path in sorted(self.entries_dir.glob("*.json")):
            rows.append(
                {
                    "key": path.stem,
                    "file": path.name,
                    "sha256": file_sha256(path),
                }
            )
        manifest = {
            "schema": CACHE_MANIFEST_SCHEMA,
            "version": M82_VERSION,
            "entry_count": len(rows),
            "entries": rows,
            "api_key_stored": False,
            "credentials_stored": False,
        }
        manifest["integrity"] = {
            "payload_sha256": canonical_sha256(manifest)
        }
        path = self.cache_dir / "manifest.json"
        write_json_atomic(path, manifest)
        return path, file_sha256(path)


class Heartbeat:
    def __init__(self, state: dict[str, Any], client: CachedGuardedGtfaClient):
        self.state = state
        self.client = client
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)

    def _run(self) -> None:
        while not self.stop_event.wait(5.0):
            stats = self.client.stats()
            print(
                "M82_HEARTBEAT="
                f"stage={self.state.get('stage')};"
                f"progress={self.state.get('stage_completed', 0)}/{self.state.get('stage_total', 0)};"
                f"credits={stats['credits_reserved']}/{self.client.effective_total_credit_cap};"
                f"network_success={stats['successful_network_requests_current_process']};"
                f"cache_hits={stats['cache_hits_current_process']};"
                f"retry429={stats['retry_429_current_process']}",
                flush=True,
            )


def _history_config(
    *,
    cutoff_epoch: int,
    limit: int,
    pagination_token: str | None,
    include_token_accounts: bool,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "transactionDetails": "full",
        "sortOrder": "desc",
        "commitment": "finalized",
        "encoding": "jsonParsed",
        "maxSupportedTransactionVersion": 1,
        "limit": int(limit),
        "filters": {
            "status": "succeeded",
            "blockTime": {"gte": int(cutoff_epoch)},
        },
    }
    if include_token_accounts:
        config["filters"]["tokenAccounts"] = "balanceChanged"
    if pagination_token:
        config["paginationToken"] = pagination_token
    return config


def _fetch_history(
    client: CachedGuardedGtfaClient,
    address: str,
    *,
    maximum_transactions: int,
    cutoff: datetime,
    include_token_accounts: bool,
    origin_prefix: str,
) -> dict[str, Any]:
    collected: dict[str, dict[str, Any]] = {}
    pagination_token: str | None = None
    pagination_remaining = False
    cutoff_epoch = int(cutoff.timestamp())

    while len(collected) < maximum_transactions:
        limit = min(100, maximum_transactions - len(collected))
        config = _history_config(
            cutoff_epoch=cutoff_epoch,
            limit=limit,
            pagination_token=pagination_token,
            include_token_accounts=include_token_accounts,
        )
        result = client.call(
            address,
            config,
            origin=f"{origin_prefix}_{address[:12]}",
        )
        rows = [dict(item) for item in result.get("data") or []]
        for item in rows:
            payload = normalize_full_transaction(item)
            if payload is None:
                continue
            signature = str(payload.get("signature") or "")
            if signature:
                collected.setdefault(signature, payload)
        next_token = result.get("paginationToken")
        if not next_token or not rows:
            pagination_token = None
            pagination_remaining = False
            break
        pagination_token = str(next_token)
        pagination_remaining = True
        if len(collected) >= maximum_transactions:
            break

    transactions = sorted(
        collected.values(),
        key=lambda item: (
            int(item.get("blockTime") or 0),
            int(item.get("slot") or 0),
            str(item.get("signature") or ""),
        ),
    )
    return {
        "transactions": transactions,
        "transaction_count": len(transactions),
        "history_complete": not pagination_remaining,
        "pagination_remaining": pagination_remaining,
    }


def _deep_from_history(
    wallet: str,
    history: dict[str, Any],
    *,
    maximum_transactions: int,
) -> dict[str, Any]:
    transactions = [dict(item) for item in history.get("transactions") or []]
    parsed = parse_public_transactions(transactions, wallet_address=wallet)
    policy = build_model_policy(maximum_transactions)
    backtest = simulate_gen4_from_public_events(parsed["events"], policy=policy)
    return {
        "wallet_address": wallet,
        "transaction_count": len(transactions),
        "history_complete": bool(history.get("history_complete")),
        "pagination_remaining": bool(history.get("pagination_remaining")),
        "parsed_event_count": len(parsed["events"]),
        "rejected_transaction_count": len(parsed["rejected"]),
        "backtest": backtest,
    }


def _guard_preflight() -> dict[str, Any]:
    db = SessionLocal()
    try:
        status = dict(get_helius_credit_guard_status(db))
        if db.new or db.dirty or db.deleted:
            raise M82PaidRpcSprintError("Guard preflight ha mutato SQLAlchemy state.")
        return status
    finally:
        db.close()


def _run_parallel_stage(
    *,
    stage: str,
    wallets: list[str],
    candidates_by_wallet: dict[str, dict[str, Any]],
    maximum_transactions: int,
    cutoff: datetime,
    client: CachedGuardedGtfaClient,
    state: dict[str, Any],
    state_path: Path,
) -> dict[str, dict[str, Any]]:
    if not wallets:
        return {}
    state["stage"] = stage
    state["stage_completed"] = 0
    state["stage_total"] = len(wallets)
    _write_state(state_path, state)
    print(
        f"M82_{stage}_START={len(wallets)};transactions={maximum_transactions}",
        flush=True,
    )
    results: dict[str, dict[str, Any]] = {}

    def worker(wallet: str) -> tuple[str, dict[str, Any]]:
        history = _fetch_history(
            client,
            wallet,
            maximum_transactions=maximum_transactions,
            cutoff=cutoff,
            include_token_accounts=True,
            origin_prefix=f"M82_{stage}",
        )
        deep = _deep_from_history(
            wallet,
            history,
            maximum_transactions=maximum_transactions,
        )
        return wallet, build_result(
            candidates_by_wallet[wallet],
            deep,
            stage=stage,
            maximum_transactions=maximum_transactions,
        )

    with ThreadPoolExecutor(max_workers=min(M82_WORKERS, len(wallets))) as pool:
        futures = {pool.submit(worker, wallet): wallet for wallet in wallets}
        for future in as_completed(futures):
            wallet = futures[future]
            try:
                wallet, row = future.result()
            except Exception as error:  # noqa: BLE001
                row = {
                    "wallet_address": wallet,
                    "stage": stage,
                    "maximum_transactions": maximum_transactions,
                    "disposition": "RPC_RETRY_REQUIRED",
                    "failure_reasons": [
                        f"{type(error).__name__}:{' '.join(str(error).split())[:220]}"
                    ],
                    "short_canary_authorized": False,
                    "micro_live_authorized": False,
                }
            results[wallet] = row
            with _STATE_LOCK:
                state.setdefault("stage_results", {}).setdefault(stage, {})[wallet] = row
                state["stage_completed"] = int(state.get("stage_completed") or 0) + 1
                _write_state(state_path, state)
            print(
                f"M82_{stage}_DONE={wallet};"
                f"closed={row.get('closed_trade_count', 0)};"
                f"pf={row.get('profit_factor', 0)};"
                f"net={row.get('net_pnl_sol', 0)};"
                f"dd={row.get('maximum_drawdown_percent', 0)};"
                f"disp={row.get('disposition')}",
                flush=True,
            )
            print(
                f"M82_{stage}_PROGRESS={state['stage_completed']}/{state['stage_total']}",
                flush=True,
            )
    return results


def _best_stage_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    stages = dict(state.get("stage_results") or {})
    by_wallet: dict[str, dict[str, Any]] = {}
    for stage in ("PASS1", "PASS2", "PASS3"):
        for wallet, row in dict(stages.get(stage) or {}).items():
            by_wallet[str(wallet)] = dict(row)
    return list(by_wallet.values())


def main() -> int:
    args = _parser().parse_args()
    if args.confirmation.strip() != M82_CONFIRMATION:
        raise M82PaidRpcSprintError(
            f"Conferma richiesta: {M82_CONFIRMATION}"
        )
    if GEN4_COPYABILITY_RAW_PARSER_VERSION != EXPECTED_PARSER_VERSION:
        raise M82PaidRpcSprintError(
            f"Parser M82 inatteso: {GEN4_COPYABILITY_RAW_PARSER_VERSION}"
        )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "m66": Path(args.m66_report).expanduser().resolve(),
        "m79": Path(args.m79_report).expanduser().resolve(),
        "m80": Path(args.m80_report).expanduser().resolve(),
        "m81_state": Path(args.m81_state).expanduser().resolve(),
    }
    expected_hashes = {
        "m66": EXPECTED_M66_SHA256,
        "m79": EXPECTED_M79_SHA256,
        "m80": EXPECTED_M80_SHA256,
        "m81_state": EXPECTED_M81_STATE_SHA256,
    }
    input_hashes: dict[str, str] = {}
    for label, path in paths.items():
        actual = file_sha256(path) if path.is_file() else ""
        if actual != expected_hashes[label]:
            raise M82PaidRpcSprintError(
                f"SHA input M82 inatteso: {label}; actual={actual or 'MISSING'}"
            )
        input_hashes[label] = actual

    m66 = _load_json(paths["m66"], "M66")
    m79 = _load_json(paths["m79"], "M79")
    m80 = _load_json(paths["m80"], "M80")
    m81_state = _load_json(paths["m81_state"], "M81 state")
    validate_inputs(m66, m79, m80, m81_state)

    suffix = EXPECTED_M81_STATE_SHA256[:16]
    state_path = output_dir / f"smartmoney-m82-paid-rpc-sprint-state-{suffix}.json"
    cache_dir = output_dir / f"smartmoney-m82-helius-rpc-cache-{suffix}"
    print(f"M82_STATE_FILE={state_path}", flush=True)
    print(f"M82_CACHE_DIR={cache_dir}", flush=True)

    if state_path.is_file():
        stale_tmp_removed = _cleanup_stale_state_tmp(state_path)
        if stale_tmp_removed:
            print("M82_STALE_TMP_REMOVED=YES", flush=True)
        state = _validate_state(
            _load_json(state_path, "M82 state"),
            input_hashes=input_hashes,
        )
        if state.get("status") == "COMPLETED":
            report_path = Path(str(state.get("report_file") or ""))
            if report_path.is_file():
                print("M82_PAID_RPC_SPRINT=ALREADY_COMPLETED", flush=True)
                print(f"M82_REPORT_FILE={report_path}", flush=True)
                print(f"M82_REPORT_SHA256={file_sha256(report_path)}", flush=True)
                return 0
            raise M82PaidRpcSprintError("M82 COMPLETED ma report assente.")
        removed_retry_rows = _repair_retry_rows_for_resume(state_path, state)
        print(f"M82_RESUME_RETRY_ROWS_RESET={len(removed_retry_rows)}", flush=True)
        if removed_retry_rows:
            print("M82_RESUME_RETRY_ROWS=" + ",".join(removed_retry_rows), flush=True)
    else:
        started = datetime.now(timezone.utc)
        state = {
            "schema": STATE_SCHEMA,
            "version": M82_VERSION,
            "scope": M82_SCOPE,
            "status": "RUNNING",
            "started_at_utc": started.isoformat(),
            "updated_at_utc": started.isoformat(),
            "history_cutoff_at_utc": (
                started - timedelta(days=M82_HISTORY_LOOKBACK_DAYS)
            ).isoformat(),
            "input_hashes": input_hashes,
            "stage": "PREFLIGHT",
            "stage_completed": 0,
            "stage_total": 0,
            "credits_reserved": 0,
            "network_attempts_reserved": 0,
            "seed_tokens": [],
            "discovery_histories": {},
            "candidates": [],
            "stage_results": {},
            "report_file": None,
            "report_sha256": None,
        }
        _write_state(state_path, state)

    guard = _guard_preflight()
    if guard.get("enforced") is not True:
        raise M82PaidRpcSprintError("HELIUS_CREDIT_GUARD_NOT_ENFORCED")
    total_remaining = int(guard.get("daily_total_credits_remaining") or 0)
    rpc_remaining = int(guard.get("daily_rpc_credits_remaining") or 0)
    already_reserved = int(state.get("credits_reserved") or 0)
    package_remaining = max(0, M82_MAX_RPC_CREDITS - already_reserved)
    additional_available = min(package_remaining, total_remaining, rpc_remaining)
    effective_total_cap = already_reserved + additional_available
    if additional_available < M82_GTFA_CREDITS_PER_REQUEST:
        raise M82PaidRpcSprintError(
            "HELIUS_RPC_CREDITS_INSUFFICIENT_FOR_M82_RESUME"
        )

    print("=== M82 STABLECOIN-HARDENED PAID RPC SPRINT ===", flush=True)
    print(f"M82_RESUME_HOTFIX={M82_RESUME_HOTFIX}", flush=True)
    print(f"PARSER_VERSION={GEN4_COPYABILITY_RAW_PARSER_VERSION}", flush=True)
    print("STABLECOIN_ROUTED_SWAP_FAIL_CLOSED=YES", flush=True)
    print("GTFA_CREDITS_PER_REQUEST=50", flush=True)
    print(f"PACKAGE_CREDIT_CAP={M82_MAX_RPC_CREDITS}", flush=True)
    print(f"EFFECTIVE_TOTAL_RUN_CAP={effective_total_cap}", flush=True)
    print(f"CURRENT_RUN_ALREADY_RESERVED={already_reserved}", flush=True)
    print(f"GUARD_TOTAL_REMAINING={total_remaining}", flush=True)
    print(f"GUARD_RPC_REMAINING={rpc_remaining}", flush=True)
    print(f"PARALLEL_WORKERS={M82_WORKERS}", flush=True)
    print("LIVE_AUTHORIZED=NO", flush=True)
    print("SIGNER_AUTHORIZED=NO", flush=True)

    client = CachedGuardedGtfaClient(
        cache_dir,
        state=state,
        state_path=state_path,
        effective_total_credit_cap=effective_total_cap,
    )
    heartbeat = Heartbeat(state, client)
    heartbeat.start()
    try:
        cutoff = datetime.fromisoformat(
            str(state["history_cutoff_at_utc"]).replace("Z", "+00:00")
        )
        if cutoff.tzinfo is None:
            cutoff = cutoff.replace(tzinfo=timezone.utc)
        cutoff = cutoff.astimezone(timezone.utc)

        seed_tokens = [dict(item) for item in state.get("seed_tokens") or []]
        if not seed_tokens:
            seed_tokens = select_discovery_tokens(m66, m81_state)
            state["seed_tokens"] = seed_tokens
            _write_state(state_path, state)
        print(
            "M82_DISCOVERY_TOKENS="
            + ",".join(str(item["token_mint"]) for item in seed_tokens),
            flush=True,
        )

        discovery_histories = dict(state.get("discovery_histories") or {})
        missing_tokens = [
            str(item["token_mint"])
            for item in seed_tokens
            if str(item["token_mint"]) not in discovery_histories
        ]
        if missing_tokens:
            state["stage"] = "DISCOVERY"
            state["stage_completed"] = len(discovery_histories)
            state["stage_total"] = len(seed_tokens)
            _write_state(state_path, state)
            print(f"M82_DISCOVERY_START={len(seed_tokens)}", flush=True)

            def discovery_worker(token: str) -> tuple[str, list[dict[str, Any]]]:
                history = _fetch_history(
                    client,
                    token,
                    maximum_transactions=M82_DISCOVERY_TX_PER_TOKEN,
                    cutoff=cutoff,
                    include_token_accounts=False,
                    origin_prefix="M82_DISCOVERY_TOKEN",
                )
                return token, [dict(item) for item in history["transactions"]]

            with ThreadPoolExecutor(max_workers=min(M82_WORKERS, len(missing_tokens))) as pool:
                futures = {
                    pool.submit(discovery_worker, token): token
                    for token in missing_tokens
                }
                for future in as_completed(futures):
                    token = futures[future]
                    token, rows = future.result()
                    # State keeps only compact discovery evidence, never full provider payloads.
                    discovery_histories[token] = [
                        {
                            "blockTime": item.get("blockTime"),
                            "transaction": {
                                "signatures": list(
                                    dict(item.get("transaction") or {}).get("signatures")
                                    or []
                                ),
                                "message": {
                                    "accountKeys": list(
                                        dict(
                                            dict(item.get("transaction") or {}).get("message")
                                            or {}
                                        ).get("accountKeys")
                                        or []
                                    )
                                },
                            },
                        }
                        for item in rows
                    ]
                    with _STATE_LOCK:
                        state["discovery_histories"] = discovery_histories
                        state["stage_completed"] = len(discovery_histories)
                        _write_state(state_path, state)
                    print(
                        f"M82_DISCOVERY_DONE={token};transactions={len(rows)}",
                        flush=True,
                    )
                    print(
                        f"M82_DISCOVERY_PROGRESS={len(discovery_histories)}/{len(seed_tokens)}",
                        flush=True,
                    )

        candidates = [dict(item) for item in state.get("candidates") or []]
        if not candidates:
            excluded = known_wallets(m66, m79, m80, m81_state)
            candidates = discover_candidates(
                {
                    token: [dict(item) for item in rows]
                    for token, rows in discovery_histories.items()
                },
                excluded_wallets=excluded,
                limit=M82_PASS1_CANDIDATES,
            )
            state["candidates"] = candidates
            _write_state(state_path, state)
        print(f"M82_NEW_CANDIDATES={len(candidates)}", flush=True)
        if not candidates:
            raise M82PaidRpcSprintError("M82_DISCOVERY_NO_NEW_CANDIDATES")

        candidates_by_wallet = {
            str(item["wallet_address"]): dict(item)
            for item in candidates
        }

        stages = dict(state.get("stage_results") or {})
        pass1_existing = dict(stages.get("PASS1") or {})
        pass1_missing = [
            wallet
            for wallet in candidates_by_wallet
            if wallet not in pass1_existing
        ]
        if pass1_missing:
            _run_parallel_stage(
                stage="PASS1",
                wallets=pass1_missing,
                candidates_by_wallet=candidates_by_wallet,
                maximum_transactions=M82_PASS1_TRANSACTIONS,
                cutoff=cutoff,
                client=client,
                state=state,
                state_path=state_path,
            )
        pass1 = dict(state.get("stage_results", {}).get("PASS1") or {})
        qualified_now = [
            row
            for row in pass1.values()
            if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"
        ]

        pass2_wallets: list[str] = []
        if len(qualified_now) < M82_REQUIRED_QUALIFIED:
            pass2_wallets = select_pass2(pass1.values())
        print(
            "M82_PASS2_SELECTED=" + ",".join(pass2_wallets),
            flush=True,
        )
        pass2_existing = dict(state.get("stage_results", {}).get("PASS2") or {})
        pass2_missing = [wallet for wallet in pass2_wallets if wallet not in pass2_existing]
        if pass2_missing:
            _run_parallel_stage(
                stage="PASS2",
                wallets=pass2_missing,
                candidates_by_wallet=candidates_by_wallet,
                maximum_transactions=M82_PASS2_TRANSACTIONS,
                cutoff=cutoff,
                client=client,
                state=state,
                state_path=state_path,
            )

        interim = _best_stage_results(state)
        qualified_now = [
            row
            for row in interim
            if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"
        ]
        pass3_wallets: list[str] = []
        if len(qualified_now) < M82_REQUIRED_QUALIFIED:
            pass3_wallets = select_pass3(interim)
        print(
            "M82_PASS3_SELECTED=" + ",".join(pass3_wallets),
            flush=True,
        )
        pass3_existing = dict(state.get("stage_results", {}).get("PASS3") or {})
        pass3_missing = [wallet for wallet in pass3_wallets if wallet not in pass3_existing]
        if pass3_missing:
            _run_parallel_stage(
                stage="PASS3",
                wallets=pass3_missing,
                candidates_by_wallet=candidates_by_wallet,
                maximum_transactions=M82_PASS3_TRANSACTIONS,
                cutoff=cutoff,
                client=client,
                state=state,
                state_path=state_path,
            )

        final_results = _best_stage_results(state)
        manifest_path, manifest_sha = client.write_manifest()
        completed = datetime.now(timezone.utc)
        report = build_final_report(
            started_at_utc=str(state["started_at_utc"]),
            completed_at_utc=completed.isoformat(),
            input_hashes=input_hashes,
            seed_tokens=seed_tokens,
            candidates=candidates,
            final_results=final_results,
            rpc_stats=client.stats(),
            cache_manifest_sha256=manifest_sha,
            effective_credit_cap=effective_total_cap,
        )
        validate_final_report(report)
        report_path = output_dir / (
            "smartmoney-m82-paid-rpc-sprint-"
            + completed.strftime("%Y%m%dT%H%M%SZ")
            + ".json"
        )
        write_json_atomic(report_path, report)
        state["status"] = "COMPLETED"
        state["stage"] = "COMPLETED"
        state["report_file"] = str(report_path)
        state["report_sha256"] = file_sha256(report_path)
        state["cache_manifest_file"] = str(manifest_path)
        state["cache_manifest_sha256"] = manifest_sha
        _write_state(state_path, state)

        summary = dict(report.get("summary") or {})
        stats = client.stats()
        print("M82_PAID_RPC_SPRINT=PASS", flush=True)
        print(f"HELIUS_RPC_CREDITS_RESERVED={stats['credits_reserved']}", flush=True)
        print(
            f"HELIUS_RPC_NETWORK_ATTEMPTS_RESERVED={stats['network_attempts_reserved']}",
            flush=True,
        )
        print(
            f"QUALIFIED_PENDING_SHORT_CANARY={summary.get('qualified_pending_short_canary', 0)}",
            flush=True,
        )
        print(
            "QUALIFIED_WALLETS="
            + ",".join(summary.get("qualified_wallets") or []),
            flush=True,
        )
        print(
            "M74_MINIMUM_TWO_WALLETS_REACHED="
            + ("YES" if summary.get("m74_minimum_two_wallets_reached") else "NO"),
            flush=True,
        )
        print("LIVE_ORDERS=0", flush=True)
        print("SIGNER_AUTHORIZED=NO", flush=True)
        print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO", flush=True)
        print(f"M82_REPORT_FILE={report_path}", flush=True)
        print(f"M82_REPORT_SHA256={file_sha256(report_path)}", flush=True)
        print(f"M82_STATE_FILE={state_path}", flush=True)
        print(f"M82_CACHE_MANIFEST_FILE={manifest_path}", flush=True)
        print(f"M82_CACHE_MANIFEST_SHA256={manifest_sha}", flush=True)
        print(f"NEXT={report.get('next_step')}", flush=True)
        return 0
    finally:
        heartbeat.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except M82PaidRpcSprintError as error:
        print(f"M82_PAID_RPC_SPRINT=FAILED:{error}", file=sys.stderr, flush=True)
        raise SystemExit(2)
