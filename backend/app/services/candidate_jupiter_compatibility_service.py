from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.constants import SOL_MINT
from backend.app.models.candidate_token_compatibility import (
    CandidateTokenCompatibility,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import JupiterSwapError
from backend.app.services.wallet_activity_service import ensure_aware


JUPITER_PASSED = "PASSED"
JUPITER_FAILED = "FAILED"
JUPITER_UNAVAILABLE = "UNAVAILABLE"
JUPITER_NOT_CHECKED = "NOT_CHECKED"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_message(error: object) -> str:
    message = str(error or "Errore Jupiter non specificato.")
    lowered = message.lower()
    if "api-key" in lowered or "x-api-key" in lowered:
        return "Errore Jupiter. Dettagli sensibili rimossi."
    return message[:500]


def _cache_item(row: CandidateTokenCompatibility) -> dict[str, Any]:
    return {
        "token_mint": row.token_mint,
        "buy_quote": bool(row.buy_quote),
        "sell_quote": bool(row.sell_quote),
        "compatible": bool(row.compatible),
        "buy_out_amount_raw": row.buy_out_amount_raw,
        "sell_out_amount_raw": row.sell_out_amount_raw,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "source": "CACHE",
        "checked_at": ensure_aware(row.checked_at).isoformat()
        if row.checked_at
        else None,
        "expires_at": ensure_aware(row.expires_at).isoformat()
        if row.expires_at
        else None,
    }


def _upsert_cache(
    db: Session,
    *,
    token_mint: str,
    fixed_buy_size_lamports: int,
    slippage_bps: int,
    status: str,
    buy_quote: bool,
    sell_quote: bool,
    compatible: bool,
    buy_out_amount_raw: int | None,
    sell_out_amount_raw: int | None,
    error_code: str | None,
    error_message: str | None,
    checked_at: datetime,
    expires_at: datetime,
) -> CandidateTokenCompatibility:
    row = (
        db.query(CandidateTokenCompatibility)
        .filter(CandidateTokenCompatibility.token_mint == token_mint)
        .filter(
            CandidateTokenCompatibility.fixed_buy_size_lamports
            == fixed_buy_size_lamports
        )
        .filter(CandidateTokenCompatibility.slippage_bps == slippage_bps)
        .first()
    )
    if row is None:
        row = CandidateTokenCompatibility(
            token_mint=token_mint,
            fixed_buy_size_lamports=fixed_buy_size_lamports,
            slippage_bps=slippage_bps,
        )
        db.add(row)

    row.status = status
    row.buy_quote = buy_quote
    row.sell_quote = sell_quote
    row.compatible = compatible
    row.buy_out_amount_raw = buy_out_amount_raw
    row.sell_out_amount_raw = sell_out_amount_raw
    row.error_code = error_code
    row.error_message = error_message
    row.checked_at = checked_at
    row.expires_at = expires_at
    db.flush()
    return row


def check_candidate_jupiter_compatibility(
    db: Session,
    tokens: list[str],
    *,
    fixed_buy_size_sol: float,
    slippage_bps: int,
    token_limit: int,
    client: JupiterSwapClient,
    cache_ttl_hours: int = 6,
    force_refresh: bool = False,
    minimum_compatibility_percent: float = 80.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    selected: list[str] = []
    for token in tokens:
        normalized = str(token or "").strip()
        if not normalized or normalized == SOL_MINT or normalized in selected:
            continue
        selected.append(normalized)
        if len(selected) >= max(1, int(token_limit)):
            break

    if not selected:
        return {
            "checked": True,
            "status": JUPITER_FAILED,
            "tokens_checked": 0,
            "tokens_compatible": 0,
            "requests": 0,
            "cache_hits": 0,
            "live_checks": 0,
            "compatibility_percent": 0.0,
            "results": [],
        }

    checked_at = ensure_aware(now) or utc_now()
    ttl_hours = max(1, min(int(cache_ttl_hours), 24))
    expires_at = checked_at + timedelta(hours=ttl_hours)
    amount_raw = max(1, int(float(fixed_buy_size_sol) * 1_000_000_000))
    effective_slippage = max(0, min(int(slippage_bps), 1000))

    results: list[dict[str, Any]] = []
    compatible_count = 0
    requests = 0
    cache_hits = 0
    live_checks = 0
    unavailable = False

    for token in selected:
        if not force_refresh:
            cached = (
                db.query(CandidateTokenCompatibility)
                .filter(CandidateTokenCompatibility.token_mint == token)
                .filter(
                    CandidateTokenCompatibility.fixed_buy_size_lamports
                    == amount_raw
                )
                .filter(
                    CandidateTokenCompatibility.slippage_bps
                    == effective_slippage
                )
                .first()
            )
            cached_expiry = ensure_aware(cached.expires_at) if cached else None
            if cached is not None and cached_expiry and cached_expiry > checked_at:
                item = _cache_item(cached)
                results.append(item)
                cache_hits += 1
                if item["compatible"]:
                    compatible_count += 1
                continue

        live_checks += 1
        item: dict[str, Any] = {
            "token_mint": token,
            "buy_quote": False,
            "sell_quote": False,
            "compatible": False,
            "buy_out_amount_raw": None,
            "sell_out_amount_raw": None,
            "error_code": None,
            "error_message": None,
            "source": "LIVE",
            "checked_at": checked_at.isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        try:
            requests += 1
            buy_quote = client.get_order(
                input_mint=SOL_MINT,
                output_mint=token,
                amount_raw=amount_raw,
                taker=None,
                slippage_bps=effective_slippage,
            )
            item["buy_quote"] = buy_quote.out_amount > 0
            item["buy_out_amount_raw"] = buy_quote.out_amount

            if buy_quote.out_amount > 0:
                requests += 1
                sell_quote = client.get_order(
                    input_mint=token,
                    output_mint=SOL_MINT,
                    amount_raw=buy_quote.out_amount,
                    taker=None,
                    slippage_bps=effective_slippage,
                )
                item["sell_quote"] = sell_quote.out_amount > 0
                item["sell_out_amount_raw"] = sell_quote.out_amount

            item["compatible"] = bool(item["buy_quote"] and item["sell_quote"])
            status = JUPITER_PASSED if item["compatible"] else JUPITER_FAILED
            if item["compatible"]:
                compatible_count += 1

            _upsert_cache(
                db,
                token_mint=token,
                fixed_buy_size_lamports=amount_raw,
                slippage_bps=effective_slippage,
                status=status,
                buy_quote=bool(item["buy_quote"]),
                sell_quote=bool(item["sell_quote"]),
                compatible=bool(item["compatible"]),
                buy_out_amount_raw=item["buy_out_amount_raw"],
                sell_out_amount_raw=item["sell_out_amount_raw"],
                error_code=None,
                error_message=None,
                checked_at=checked_at,
                expires_at=expires_at,
            )

        except JupiterSwapError as error:
            item["error_code"] = error.code
            item["error_message"] = _safe_error_message(error)
            if error.code == "JUPITER_NOT_CONFIGURED":
                unavailable = True
                results.append(item)
                break

            _upsert_cache(
                db,
                token_mint=token,
                fixed_buy_size_lamports=amount_raw,
                slippage_bps=effective_slippage,
                status=JUPITER_FAILED,
                buy_quote=bool(item["buy_quote"]),
                sell_quote=bool(item["sell_quote"]),
                compatible=False,
                buy_out_amount_raw=item["buy_out_amount_raw"],
                sell_out_amount_raw=item["sell_out_amount_raw"],
                error_code=error.code,
                error_message=item["error_message"],
                checked_at=checked_at,
                expires_at=expires_at,
            )
        except Exception as error:
            item["error_code"] = "JUPITER_UNEXPECTED_ERROR"
            item["error_message"] = _safe_error_message(error)
            _upsert_cache(
                db,
                token_mint=token,
                fixed_buy_size_lamports=amount_raw,
                slippage_bps=effective_slippage,
                status=JUPITER_FAILED,
                buy_quote=bool(item["buy_quote"]),
                sell_quote=bool(item["sell_quote"]),
                compatible=False,
                buy_out_amount_raw=item["buy_out_amount_raw"],
                sell_out_amount_raw=item["sell_out_amount_raw"],
                error_code=item["error_code"],
                error_message=item["error_message"],
                checked_at=checked_at,
                expires_at=expires_at,
            )

        results.append(item)

    checked = len(results)
    compatibility = compatible_count / checked * 100.0 if checked else 0.0
    if unavailable:
        status = JUPITER_UNAVAILABLE
    elif checked > 0 and compatibility >= float(minimum_compatibility_percent):
        status = JUPITER_PASSED
    else:
        status = JUPITER_FAILED

    return {
        "checked": True,
        "status": status,
        "tokens_checked": checked,
        "tokens_compatible": compatible_count,
        "requests": requests,
        "cache_hits": cache_hits,
        "live_checks": live_checks,
        "compatibility_percent": round(compatibility, 4),
        "results": results,
    }
