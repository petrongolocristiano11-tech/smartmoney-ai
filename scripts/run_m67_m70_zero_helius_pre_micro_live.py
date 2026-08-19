from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_DEFAULT_PUBLIC_RPC_URL,
    M64_EXPECTED_ALEMBIC_HEAD,
    M64_EXPECTED_DATABASE,
    canonical_sha256,
    file_sha256,
    parse_public_transactions,
    readonly_database_url,
    write_json_atomic,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    M67_M70_CACHE_SCHEMA,
    M67_M70_DEFAULT_POLICY,
    M67_M70_RUN_CONFIRMATION,
    M67M70ZeroHeliusError,
    build_rpc_evidence,
    build_unified_local_snapshot,
    evaluate_zero_helius_pre_micro_live,
    simulate_gen4_from_public_events,
    summarize_signature_activity,
    utc_now,
    validate_policy,
)


class PublicRpcBudgetExhausted(M67M70ZeroHeliusError):
    pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M67-M70 Zero-Helius: evidenze locali unificate, prescreen RPC "
            "pubblico, backtest Gen4, consenso e foundation Micro Live disarmata."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rpc-url", default=M64_DEFAULT_PUBLIC_RPC_URL)
    parser.add_argument("--database-url-env", default="DATABASE_PUBLIC_URL")
    parser.add_argument("--wallet-limit", type=int, default=500)
    parser.add_argument("--maximum-deep-wallets", type=int, default=3)
    parser.add_argument("--maximum-signatures-per-wallet", type=int, default=150)
    parser.add_argument("--public-rpc-request-cap", type=int, default=600)
    parser.add_argument("--cache-input", default="")
    parser.add_argument("--m64-report", action="append", default=[])
    parser.add_argument("--m65-report", action="append", default=[])
    parser.add_argument("--fixture", default="")
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M67M70ZeroHeliusError(f"JSON non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M67M70ZeroHeliusError(f"JSON root non oggetto: {path.name}.")
    return value


def _load_reports(paths: list[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for value in paths:
        path = Path(str(value)).expanduser().resolve()
        if not path.is_file():
            raise M67M70ZeroHeliusError(f"Report esterno non trovato: {path.name}.")
        result.append(_load_json(path))
    return result


def _cache_payload(cache: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in cache.items() if name != "integrity"}


def _load_cache(path_text: str, *, public_origin: str) -> dict[str, Any]:
    if not str(path_text or "").strip():
        cache: dict[str, Any] = {
            "schema": M67_M70_CACHE_SCHEMA,
            "public_origin": public_origin,
            "entries": {},
        }
        cache["integrity"] = {"payload_sha256": canonical_sha256(cache)}
        return cache
    path = Path(path_text).expanduser().resolve()
    cache = _load_json(path)
    if cache.get("schema") != M67_M70_CACHE_SCHEMA:
        raise M67M70ZeroHeliusError("Schema cache RPC pubblico M67 inatteso.")
    if str(cache.get("public_origin") or "") != public_origin:
        raise M67M70ZeroHeliusError("Origin cache RPC pubblico M67 inattesa.")
    expected = str(dict(cache.get("integrity") or {}).get("payload_sha256") or "")
    if len(expected) != 64 or expected != canonical_sha256(_cache_payload(cache)):
        raise M67M70ZeroHeliusError("Hash cache RPC pubblico M67 non valido.")
    entries = dict(cache.get("entries") or {})
    for key, entry_value in entries.items():
        entry = dict(entry_value or {})
        if str(entry.get("result_sha256") or "") != canonical_sha256(entry.get("result")):
            raise M67M70ZeroHeliusError(f"Entry cache RPC corrotta: {key[:12]}.")
    cache["entries"] = entries
    return cache


def _finalize_cache(cache: dict[str, Any]) -> dict[str, Any]:
    result = _cache_payload(cache)
    result["integrity"] = {"payload_sha256": canonical_sha256(result)}
    return result


class CachedBudgetedPublicRpc:
    def __init__(
        self,
        url: str,
        *,
        cache: dict[str, Any],
        request_cap: int,
        maximum_attempts: int,
        throttle_seconds: float,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        parsed = urlsplit(str(url or "").strip())
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme != "https" or not hostname:
            raise M67M70ZeroHeliusError("RPC pubblico M67 deve usare HTTPS.")
        if "helius" in hostname:
            raise M67M70ZeroHeliusError("M67 rifiuta esplicitamente endpoint Helius.")
        if parsed.username or parsed.password:
            raise M67M70ZeroHeliusError("RPC pubblico M67 non deve avere credenziali.")
        self.url = str(url).strip()
        self.public_origin = f"{parsed.scheme}://{hostname}"
        self.cache = cache
        self.request_cap = max(1, int(request_cap))
        self.maximum_attempts = max(1, min(int(maximum_attempts), 4))
        self.throttle_seconds = max(0.0, float(throttle_seconds))
        self.client = client or httpx.Client(timeout=45.0)
        self._owns_client = client is None
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.last_request_at: float | None = None
        self.requests = 0
        self.cache_hits = 0
        self.retry_429 = 0
        self.retry_5xx = 0
        self.retry_network = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _throttle(self) -> None:
        if self.last_request_at is None:
            return
        remaining = self.throttle_seconds - (self.monotonic_fn() - self.last_request_at)
        if remaining > 0:
            self.sleep_fn(remaining)

    def _backoff(self, attempt: int, retry_after: str | None = None) -> None:
        delay = min(8.0, 0.75 * (2 ** max(0, attempt - 1)))
        if retry_after:
            try:
                delay = max(delay, min(30.0, float(retry_after)))
            except ValueError:
                pass
        self.sleep_fn(delay)

    def call(self, method: str, params: list[Any]) -> Any:
        request_contract = {
            "public_origin": self.public_origin,
            "method": method,
            "params": params,
        }
        key = canonical_sha256(request_contract)
        entries = dict(self.cache.setdefault("entries", {}))
        cached = entries.get(key)
        if cached is not None:
            entry = dict(cached)
            if entry.get("request") != request_contract:
                raise M67M70ZeroHeliusError("Collisione cache RPC pubblico M67.")
            if str(entry.get("result_sha256") or "") != canonical_sha256(entry.get("result")):
                raise M67M70ZeroHeliusError("Hash entry cache RPC pubblico M67 non valido.")
            self.cache_hits += 1
            return entry.get("result")

        last_error: Exception | None = None
        for attempt in range(1, self.maximum_attempts + 1):
            if self.requests >= self.request_cap:
                raise PublicRpcBudgetExhausted(
                    f"Cap RPC pubblico raggiunto: {self.request_cap}."
                )
            self._throttle()
            self.requests += 1
            self.last_request_at = self.monotonic_fn()
            try:
                response = self.client.post(
                    self.url,
                    json={
                        "jsonrpc": "2.0",
                        "id": self.requests,
                        "method": method,
                        "params": params,
                    },
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code == 429:
                    self.retry_429 += 1
                    if attempt < self.maximum_attempts:
                        self._backoff(attempt, response.headers.get("Retry-After"))
                        continue
                if 500 <= response.status_code <= 599:
                    self.retry_5xx += 1
                    if attempt < self.maximum_attempts:
                        self._backoff(attempt)
                        continue
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    raise M67M70ZeroHeliusError("Risposta JSON-RPC M67 inattesa.")
                if body.get("error"):
                    code = dict(body.get("error") or {}).get("code")
                    raise M67M70ZeroHeliusError(
                        f"RPC pubblico {method} fallito; code={code}."
                    )
                result = body.get("result")
                entry = {
                    "request": request_contract,
                    "result": result,
                    "result_sha256": canonical_sha256(result),
                }
                self.cache.setdefault("entries", {})[key] = entry
                return result
            except (httpx.HTTPError, ValueError, M67M70ZeroHeliusError) as error:
                last_error = error
                if isinstance(error, httpx.HTTPError):
                    self.retry_network += 1
                if attempt < self.maximum_attempts:
                    self._backoff(attempt)
                    continue
        raise M67M70ZeroHeliusError(
            f"RPC pubblico non disponibile per {method}: {type(last_error).__name__}."
        ) from None

    def stats(self) -> dict[str, Any]:
        return {
            "public_origin": self.public_origin,
            "requests": self.requests,
            "request_cap": self.request_cap,
            "cache_hits": self.cache_hits,
            "retry_429": self.retry_429,
            "retry_5xx": self.retry_5xx,
            "retry_network": self.retry_network,
            "maximum_attempts": self.maximum_attempts,
            "throttle_seconds": self.throttle_seconds,
            "helius_requests": 0,
        }


def _signature_page(
    rpc: CachedBudgetedPublicRpc,
    wallet: str,
    *,
    limit: int,
    before: str | None = None,
) -> list[dict[str, Any]]:
    config: dict[str, Any] = {"commitment": "finalized", "limit": int(limit)}
    if before:
        config["before"] = before
    result = rpc.call("getSignaturesForAddress", [wallet, config])
    if not isinstance(result, list):
        raise M67M70ZeroHeliusError(f"Elenco firme RPC non valido: {wallet}.")
    return [dict(item) for item in result if isinstance(item, dict)]


def _scan_activity(
    rpc: CachedBudgetedPublicRpc,
    wallets: list[str],
    *,
    now: datetime,
    policy: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    activity: dict[str, dict[str, Any]] = {}
    first_pages: dict[str, list[dict[str, Any]]] = {}
    page_limit = int(policy["signature_page_limit"])
    for wallet in sorted(wallets):
        rows = _signature_page(rpc, wallet, limit=page_limit)
        first_pages[wallet] = rows
        summary = summarize_signature_activity(rows, now=now, policy=policy)
        summary["page_rows"] = len(rows)
        summary["page_limit"] = page_limit
        summary["page_saturated"] = len(rows) >= page_limit
        activity[wallet] = summary
    return activity, first_pages


def _collect_deep_history(
    rpc: CachedBudgetedPublicRpc,
    wallet: str,
    *,
    first_page: list[dict[str, Any]],
    now: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    cutoff = now - timedelta(days=int(policy["activity_lookback_days"]))
    maximum = int(policy["maximum_signatures_per_deep_wallet"])
    page_limit = int(policy["signature_page_limit"])
    collected: dict[str, dict[str, Any]] = {}
    page = list(first_page)
    requested_limit = page_limit
    before: str | None = None
    boundary_reached = False
    budget_exhausted = False

    while len(collected) < maximum and not boundary_reached:
        if before is not None:
            next_limit = min(page_limit, maximum - len(collected))
            requested_limit = next_limit
            try:
                page = _signature_page(rpc, wallet, limit=next_limit, before=before)
            except PublicRpcBudgetExhausted:
                budget_exhausted = True
                break
        if not page:
            boundary_reached = True
            break
        for item in page:
            block_time = item.get("blockTime")
            if block_time is None:
                continue
            timestamp = datetime.fromtimestamp(int(block_time), tz=timezone.utc)
            if timestamp < cutoff:
                boundary_reached = True
                break
            signature = str(item.get("signature") or "")
            if signature and item.get("err") is None:
                collected.setdefault(signature, item)
            if len(collected) >= maximum:
                break
        before = str((page[-1] or {}).get("signature") or "") if page else None
        if len(collected) >= maximum:
            break
        if boundary_reached or len(page) < requested_limit or not before:
            boundary_reached = True
            break

    signatures = sorted(
        collected.values(),
        key=lambda item: (
            int(item.get("blockTime") or 0),
            int(item.get("slot") or 0),
            str(item.get("signature") or ""),
        ),
    )
    transactions: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for item in signatures:
        signature = str(item.get("signature") or "")
        try:
            result = rpc.call(
                "getTransaction",
                [
                    signature,
                    {
                        "commitment": "finalized",
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            )
        except PublicRpcBudgetExhausted:
            budget_exhausted = True
            break
        except M67M70ZeroHeliusError:
            unavailable.append(signature)
            continue
        if not isinstance(result, dict):
            unavailable.append(signature)
            continue
        payload = dict(result)
        payload.setdefault("signature", signature)
        transactions.append(payload)

    parsed = parse_public_transactions(transactions, wallet_address=wallet)
    backtest = simulate_gen4_from_public_events(parsed["events"], policy=policy)
    transaction_hashes = [
        {
            "signature": str(item.get("signature") or ""),
            "transaction_sha256": canonical_sha256(item),
        }
        for item in transactions
    ]
    history_complete = (
        boundary_reached
        and not budget_exhausted
        and not unavailable
        and len(transactions) == len(signatures)
    )
    return {
        "wallet_address": wallet,
        "cutoff_at_utc": cutoff.isoformat(),
        "signature_count": len(signatures),
        "transaction_count": len(transactions),
        "unavailable_signatures": unavailable,
        "signature_limit_reached": len(collected) >= maximum and not boundary_reached,
        "public_rpc_budget_exhausted": budget_exhausted,
        "history_complete": history_complete,
        "parsed_event_count": len(parsed["events"]),
        "rejected_transaction_count": len(parsed["rejected"]),
        "events": parsed["events"],
        "transaction_hashes": transaction_hashes,
        "backtest": backtest,
        "historical_jupiter_quotes_invented": False,
        "helius_requests": 0,
    }


def _database_snapshot(
    database_public_url: str,
    *,
    m64_reports: list[dict[str, Any]],
    m65_reports: list[dict[str, Any]],
    limit: int,
    now: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    engine = create_engine(
        readonly_database_url(database_public_url),
        future=True,
        pool_pre_ping=True,
    )
    connection = None
    transaction = None
    try:
        connection = engine.connect()
        transaction = connection.begin()
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        database_name = str(
            connection.execute(text("SELECT current_database()" )).scalar_one()
        )
        read_only = str(
            connection.execute(text("SHOW transaction_read_only")).scalar_one()
        ).lower()
        alembic_head = str(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        )
        if database_name != M64_EXPECTED_DATABASE:
            raise M67M70ZeroHeliusError(
                f"Database inatteso: {database_name}; atteso={M64_EXPECTED_DATABASE}."
            )
        if read_only != "on":
            raise M67M70ZeroHeliusError("Transazione M67 non read-only.")
        if alembic_head != M64_EXPECTED_ALEMBIC_HEAD:
            raise M67M70ZeroHeliusError(
                f"Alembic head inattesa: {alembic_head}; attesa={M64_EXPECTED_ALEMBIC_HEAD}."
            )
        with Session(bind=connection, autoflush=False, expire_on_commit=False) as db:
            snapshot = build_unified_local_snapshot(
                db,
                m64_reports=m64_reports,
                m65_reports=m65_reports,
                limit=limit,
                now=now,
            )
            if db.new or db.dirty or db.deleted:
                raise M67M70ZeroHeliusError(
                    "Snapshot M67 ha prodotto stato SQLAlchemy mutabile."
                )
        return snapshot, {
            "database_name": database_name,
            "transaction_read_only": read_only,
            "alembic_head": alembic_head,
        }
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()
        engine.dispose()


def _fixture_run(fixture_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    fixture = _load_json(fixture_path)
    expected = str(dict(fixture.get("integrity") or {}).get("fixture_sha256") or "")
    payload = {name: value for name, value in fixture.items() if name != "integrity"}
    if len(expected) != 64 or expected != canonical_sha256(payload):
        raise M67M70ZeroHeliusError("Hash fixture M67-M70 non valido.")
    local_snapshot = dict(fixture.get("local_snapshot") or {})
    rpc_evidence = dict(fixture.get("rpc_evidence") or {})
    report = evaluate_zero_helius_pre_micro_live(
        local_snapshot,
        rpc_evidence,
        policy=dict(fixture.get("policy") or {}),
        evaluated_at=datetime.fromisoformat(
            str(fixture.get("evaluated_at_utc")).replace("Z", "+00:00")
        ),
    )
    return local_snapshot, rpc_evidence, report


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation or "").strip() != M67_M70_RUN_CONFIRMATION:
        raise M67M70ZeroHeliusError(
            f"Conferma richiesta: {M67_M70_RUN_CONFIRMATION}."
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M67M70ZeroHeliusError("Output M67-M70 deve restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)
    policy = validate_policy(
        {
            **M67_M70_DEFAULT_POLICY,
            "wallet_inventory_limit": max(1, min(int(args.wallet_limit), 500)),
            "maximum_deep_wallets": max(1, min(int(args.maximum_deep_wallets), 3)),
            "maximum_signatures_per_deep_wallet": max(
                25,
                min(int(args.maximum_signatures_per_wallet), 500),
            ),
            "public_rpc_request_cap": max(
                30,
                min(int(args.public_rpc_request_cap), 2000),
            ),
        }
    )
    started = utc_now()
    fixture_value = str(args.fixture or "").strip()
    cache: dict[str, Any]
    database_contract: dict[str, Any]
    if fixture_value:
        local_snapshot, rpc_evidence, report = _fixture_run(
            Path(fixture_value).expanduser().resolve()
        )
        cache = _finalize_cache(
            {
                "schema": M67_M70_CACHE_SCHEMA,
                "public_origin": "https://api.mainnet-beta.solana.com",
                "entries": {},
            }
        )
        database_contract = {
            "database_name": None,
            "transaction_read_only": "not_applicable_fixture",
            "alembic_head": None,
        }
        execution_mode = "OFFLINE_SIGNED_FIXTURE"
    else:
        environment_name = str(args.database_url_env or "").strip()
        database_public_url = str(os.getenv(environment_name) or "").strip()
        if not database_public_url:
            raise M67M70ZeroHeliusError(
                f"Variabile {environment_name} assente; nessun fallback a DATABASE_URL."
            )
        m64_reports = _load_reports(list(args.m64_report or []))
        m65_reports = _load_reports(list(args.m65_report or []))
        local_snapshot, database_contract = _database_snapshot(
            database_public_url,
            m64_reports=m64_reports,
            m65_reports=m65_reports,
            limit=int(policy["wallet_inventory_limit"]),
            now=started,
        )
        parsed_url = urlsplit(str(args.rpc_url or ""))
        public_origin = f"{parsed_url.scheme}://{str(parsed_url.hostname or '').lower()}"
        cache = _load_cache(str(args.cache_input or ""), public_origin=public_origin)
        rpc_client = CachedBudgetedPublicRpc(
            args.rpc_url,
            cache=cache,
            request_cap=int(policy["public_rpc_request_cap"]),
            maximum_attempts=int(policy["public_rpc_maximum_attempts"]),
            throttle_seconds=float(policy["public_rpc_throttle_seconds"]),
        )
        try:
            wallets = [
                str(item.get("wallet_address") or "")
                for item in local_snapshot.get("candidates") or []
            ]
            activity, first_pages = _scan_activity(
                rpc_client,
                wallets,
                now=started,
                policy=policy,
            )
            m65_failed = {
                str(item.get("wallet_address") or "")
                for item in local_snapshot.get("candidates") or []
                if str(dict(item.get("m65_gate") or {}).get("status"))
                == "FAIL_ECONOMIC"
            }
            ranked = sorted(
                [
                    wallet
                    for wallet in wallets
                    if activity.get(wallet, {}).get("deep_history_candidate")
                    and wallet not in m65_failed
                ],
                key=lambda wallet: (
                    -int(activity[wallet].get("transactions_7d") or 0),
                    -int(activity[wallet].get("active_days_7d") or 0),
                    wallet,
                ),
            )[: int(policy["maximum_deep_wallets"])]
            deep: dict[str, dict[str, Any]] = {}
            for wallet in ranked:
                deep[wallet] = _collect_deep_history(
                    rpc_client,
                    wallet,
                    first_page=first_pages[wallet],
                    now=started,
                    policy=policy,
                )
            cache = _finalize_cache(cache)
            rpc_evidence = build_rpc_evidence(
                activity_rows=activity,
                deep_rows=deep,
                rpc_stats=rpc_client.stats(),
                cache=cache,
                policy=policy,
                collected_at=utc_now(),
            )
        finally:
            rpc_client.close()
        report = evaluate_zero_helius_pre_micro_live(
            local_snapshot,
            rpc_evidence,
            policy=policy,
            evaluated_at=utc_now(),
        )
        execution_mode = "PRODUCTION_DB_READ_ONLY_PLUS_PUBLIC_SOLANA_RPC"

    report["source"]["execution_mode"] = execution_mode
    report["source"]["database_contract"] = database_contract
    report["integrity"]["report_payload_sha256"] = canonical_sha256(
        {name: value for name, value in report.items() if name != "integrity"}
    )
    timestamp = started.strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = output_dir / f"smartmoney-m67-unified-local-snapshot-{timestamp}.json"
    rpc_path = output_dir / f"smartmoney-m67-public-rpc-evidence-{timestamp}.json"
    cache_path = output_dir / f"smartmoney-m67-public-rpc-cache-{timestamp}.json"
    report_path = output_dir / f"smartmoney-m67-m70-pre-micro-live-report-{timestamp}.json"
    write_json_atomic(snapshot_path, local_snapshot)
    write_json_atomic(rpc_path, rpc_evidence)
    write_json_atomic(cache_path, cache)
    write_json_atomic(report_path, report)

    summary = report["summary"]
    rpc_stats = dict(rpc_evidence.get("rpc") or {})
    print("=== M67-M70 ZERO-HELIUS PRE-MICRO-LIVE FOUNDATION ===")
    print("M67_M70_EVALUATION=PASS")
    print(f"WALLETS_EVALUATED={summary['wallets_evaluated']}")
    print(f"ACTIVE_PUBLIC_RPC_CANDIDATES={summary['wallets_active_candidates']}")
    print(f"DEEP_WALLETS_ANALYZED={summary['wallets_deep_analyzed']}")
    print(
        "QUALIFIED_PENDING_SHORT_CANARY="
        + str(summary["wallets_qualified_pending_canary"])
    )
    print(
        "NEEDS_MORE_PUBLIC_RPC_HISTORY="
        + str(summary["wallets_needing_more_public_history"])
    )
    print(f"SELECTED_WALLETS={summary['selected_wallets']}")
    print(
        "MULTI_WALLET_MINIMUM_REACHED="
        + ("YES" if summary["multi_wallet_minimum_reached"] else "NO")
    )
    print(f"PUBLIC_RPC_REQUEST_CAP={policy['public_rpc_request_cap']}")
    print(f"PUBLIC_RPC_REQUESTS={int(rpc_stats.get('requests') or 0)}")
    print(f"PUBLIC_RPC_CACHE_HITS={int(rpc_stats.get('cache_hits') or 0)}")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_AUTHORIZED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("AUTOMATIC_LIVE_ACTIVATION=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HISTORICAL_JUPITER_QUOTES_INVENTED=NO")
    print("PRE_MICRO_LIVE_FOUNDATION=PREPARED_DISARMED")
    print(f"LOCAL_SNAPSHOT_FILE={snapshot_path}")
    print(f"LOCAL_SNAPSHOT_SHA256={file_sha256(snapshot_path)}")
    print(f"PUBLIC_RPC_EVIDENCE_FILE={rpc_path}")
    print(f"PUBLIC_RPC_EVIDENCE_SHA256={file_sha256(rpc_path)}")
    print(f"PUBLIC_RPC_CACHE_FILE={cache_path}")
    print(f"PUBLIC_RPC_CACHE_SHA256={file_sha256(cache_path)}")
    print(f"PRE_MICRO_LIVE_REPORT_FILE={report_path}")
    print(f"PRE_MICRO_LIVE_REPORT_SHA256={file_sha256(report_path)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        message = " ".join(str(error).split()) or "Nessun dettaglio disponibile."
        print(
            "M67_M70_EVALUATION=FAILED "
            f"type={type(error).__name__} message={message}"
        )
        raise SystemExit(1) from None
