from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.constants import SOL_MINT
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.solana_rpc import SolanaRpcClient


LAMPORTS_PER_SOL = 1_000_000_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class TokenMarketMetrics:
    liquidity_usd: float
    market_cap_usd: float
    volume_24h_usd: float
    pair_count: int
    raw: list[dict[str, Any]]


class DexScreenerClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.base_url = (base_url or settings.DEXSCREENER_API_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds or settings.TOKEN_SAFETY_TIMEOUT_SECONDS
        self.transport = transport

    def get_token_metrics(self, token_mint: str) -> TokenMarketMetrics:
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.get(
                    f"{self.base_url}/token-pairs/v1/solana/{token_mint}",
                    headers={"Accept": "application/json"},
                )
        except httpx.TimeoutException as exception:
            raise LiveTradingError(
                "Timeout DexScreener durante il controllo token.",
                code="DEXSCREENER_TIMEOUT",
                status_code=504,
            ) from exception
        except httpx.HTTPError as exception:
            raise LiveTradingError(
                "Errore di rete DexScreener.",
                code="DEXSCREENER_NETWORK_ERROR",
                status_code=502,
            ) from exception

        if response.is_error:
            raise LiveTradingError(
                f"DexScreener HTTP {response.status_code}.",
                code="DEXSCREENER_HTTP_ERROR",
                status_code=502,
            )

        try:
            payload = response.json()
        except ValueError as exception:
            raise LiveTradingError(
                "DexScreener ha restituito una risposta non JSON.",
                code="DEXSCREENER_INVALID_RESPONSE",
                status_code=502,
            ) from exception

        pairs = payload if isinstance(payload, list) else payload.get("pairs", []) if isinstance(payload, dict) else []
        solana_pairs = [pair for pair in pairs if isinstance(pair, dict) and pair.get("chainId") in (None, "solana")]

        liquidity = max(
            (safe_float((pair.get("liquidity") or {}).get("usd")) for pair in solana_pairs),
            default=0.0,
        )
        market_cap = max(
            (safe_float(pair.get("marketCap") or pair.get("fdv")) for pair in solana_pairs),
            default=0.0,
        )
        volume = sum(
            safe_float((pair.get("volume") or {}).get("h24"))
            for pair in solana_pairs
        )

        return TokenMarketMetrics(
            liquidity_usd=round(liquidity, 2),
            market_cap_usd=round(market_cap, 2),
            volume_24h_usd=round(volume, 2),
            pair_count=len(solana_pairs),
            raw=solana_pairs[:10],
        )


class RugCheckClient:
    def __init__(
        self,
        *,
        url_template: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.url_template = (url_template if url_template is not None else settings.RUGCHECK_API_URL).strip()
        self.api_key = (api_key if api_key is not None else settings.RUGCHECK_API_KEY).strip()
        self.timeout_seconds = timeout_seconds or settings.TOKEN_SAFETY_TIMEOUT_SECONDS
        self.transport = transport

    @property
    def configured(self) -> bool:
        return bool(self.url_template)

    def get_report(self, token_mint: str) -> dict[str, Any] | None:
        if not self.configured:
            return None

        url = self.url_template.format(mint=token_mint)
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key

        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exception:
            raise LiveTradingError(
                "RugCheck esterno non disponibile.",
                code="RUGCHECK_UNAVAILABLE",
                status_code=502,
            ) from exception

        if not isinstance(payload, dict):
            raise LiveTradingError(
                "Risposta RugCheck esterna non valida.",
                code="RUGCHECK_INVALID_RESPONSE",
                status_code=502,
            )

        return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def _mint_info(rpc_client: SolanaRpcClient, token_mint: str) -> tuple[int, bool, bool]:
    account = rpc_client.call(
        "getAccountInfo",
        [token_mint, {"encoding": "jsonParsed", "commitment": "confirmed"}],
    )
    value = account.get("value") if isinstance(account, dict) else None
    parsed = (((value or {}).get("data") or {}).get("parsed") or {}) if isinstance(value, dict) else {}
    info = parsed.get("info") if isinstance(parsed, dict) else {}
    info = info if isinstance(info, dict) else {}

    decimals = safe_int(info.get("decimals"), 0)
    mint_authority_enabled = bool(info.get("mintAuthority"))
    freeze_authority_enabled = bool(info.get("freezeAuthority"))
    return decimals, mint_authority_enabled, freeze_authority_enabled


def _top_holder_percent(rpc_client: SolanaRpcClient, token_mint: str) -> float:
    supply_result = rpc_client.call(
        "getTokenSupply",
        [token_mint, {"commitment": "confirmed"}],
    )
    largest_result = rpc_client.call(
        "getTokenLargestAccounts",
        [token_mint, {"commitment": "confirmed"}],
    )

    supply_value = (supply_result.get("value") or {}) if isinstance(supply_result, dict) else {}
    total_supply = safe_float(supply_value.get("uiAmountString") or supply_value.get("uiAmount"), 0.0)
    largest_values = (largest_result.get("value") or []) if isinstance(largest_result, dict) else []

    if total_supply <= 0:
        return 100.0

    largest = max(
        (safe_float(item.get("uiAmountString") or item.get("uiAmount")) for item in largest_values if isinstance(item, dict)),
        default=0.0,
    )
    return round(max(0.0, min(100.0, largest / total_supply * 100)), 4)


def _parse_rugcheck(report: dict[str, Any] | None) -> tuple[bool | None, bool | None, int | None]:
    if report is None:
        return None, None, None

    rugged_value = report.get("rugged", report.get("isRug"))
    rugged = bool(rugged_value) if rugged_value is not None else None
    result = str(report.get("result") or report.get("status") or "").strip().lower()
    score = safe_int(report.get("score", report.get("riskScore")), -1)
    risk_score = score if score >= 0 else None

    if rugged is True:
        passed = False
    elif result in {"good", "safe", "pass", "passed", "verified"}:
        passed = True
    elif result in {"danger", "warning", "fail", "failed", "rugged"}:
        passed = False
    elif rugged is False:
        passed = True
    else:
        passed = None

    return rugged, passed, risk_score


def _error_name(exception: Exception) -> str:
    code = getattr(exception, "code", None)
    return str(code or type(exception).__name__)


def refresh_token_safety_snapshot(
    db: Session,
    *,
    token_mint: str,
    rpc_client: SolanaRpcClient | None = None,
    jupiter_client: JupiterSwapClient | None = None,
    dex_client: DexScreenerClient | None = None,
    rugcheck_client: RugCheckClient | None = None,
) -> TokenSafetySnapshot:
    """Refresh a token snapshot without losing all results on one provider error.

    Manual scans must always produce a visible, conservative snapshot. Every
    unavailable source is recorded in ``reasons``/``raw_payload`` and increases
    risk so fail-closed BUY policy remains safe.
    """
    token_mint = str(token_mint or "").strip()
    if not 32 <= len(token_mint) <= 44 or token_mint == SOL_MINT:
        raise LiveTradingError(
            "Token mint non valido per il controllo sicurezza.",
            code="INVALID_TOKEN_MINT",
            status_code=422,
        )

    rpc_client = rpc_client or SolanaRpcClient()
    jupiter_client = jupiter_client or JupiterSwapClient()
    dex_client = dex_client or DexScreenerClient()
    rugcheck_client = rugcheck_client or RugCheckClient()

    provider_errors: dict[str, str] = {}
    successful_sources: list[str] = []

    decimals = 6
    mint_authority_enabled = False
    freeze_authority_enabled = False
    try:
        (
            decimals,
            mint_authority_enabled,
            freeze_authority_enabled,
        ) = _mint_info(rpc_client, token_mint)
        successful_sources.append("ONCHAIN_MINT")
    except Exception as exception:
        provider_errors["mint_info"] = _error_name(exception)

    top_holder_percent = 100.0
    try:
        top_holder_percent = _top_holder_percent(rpc_client, token_mint)
        successful_sources.append("ONCHAIN_HOLDERS")
    except Exception as exception:
        provider_errors["holders"] = _error_name(exception)

    market = TokenMarketMetrics(
        liquidity_usd=0.0,
        market_cap_usd=0.0,
        volume_24h_usd=0.0,
        pair_count=0,
        raw=[],
    )
    try:
        market = dex_client.get_token_metrics(token_mint)
        successful_sources.append("DEXSCREENER")
    except Exception as exception:
        provider_errors["dexscreener"] = _error_name(exception)

    honeypot = False
    sell_quote_error: str | None = None
    sell_amount_raw = max(1, 10 ** max(0, min(decimals, 9)))
    try:
        sell_quote = jupiter_client.get_order(
            input_mint=token_mint,
            output_mint=SOL_MINT,
            amount_raw=sell_amount_raw,
            taker=None,
            slippage_bps=500,
        )
        successful_sources.append("JUPITER")
        if sell_quote.out_amount <= 0:
            honeypot = True
            sell_quote_error = "ZERO_SELL_OUTPUT"
    except Exception as exception:
        honeypot = True
        sell_quote_error = _error_name(exception)
        provider_errors["jupiter"] = sell_quote_error

    rugcheck_report = None
    try:
        rugcheck_report = rugcheck_client.get_report(token_mint)
        if rugcheck_report is not None:
            successful_sources.append("RUGCHECK")
    except Exception as exception:
        provider_errors["rugcheck"] = _error_name(exception)

    rugged, rugcheck_passed, external_risk_score = _parse_rugcheck(
        rugcheck_report
    )

    risk_score = 0
    reasons: list[str] = []

    if "mint_info" in provider_errors:
        risk_score += 15
        reasons.append("MINT_INFO_UNAVAILABLE")
    if "holders" in provider_errors:
        risk_score += 25
        reasons.append("HOLDER_DATA_UNAVAILABLE")
    if "dexscreener" in provider_errors:
        risk_score += 20
        reasons.append("MARKET_DATA_UNAVAILABLE")
    if "jupiter" in provider_errors:
        reasons.append("JUPITER_SELL_CHECK_UNAVAILABLE")
    if "rugcheck" in provider_errors:
        reasons.append("RUGCHECK_UNAVAILABLE")

    if mint_authority_enabled:
        risk_score += 20
        reasons.append("MINT_AUTHORITY_ENABLED")
    if freeze_authority_enabled:
        risk_score += 20
        reasons.append("FREEZE_AUTHORITY_ENABLED")
    if top_holder_percent > 50:
        risk_score += 25
        reasons.append("TOP_HOLDER_ABOVE_50_PERCENT")
    elif top_holder_percent > 35:
        risk_score += 15
        reasons.append("TOP_HOLDER_ABOVE_35_PERCENT")
    elif top_holder_percent > 20:
        risk_score += 8
        reasons.append("TOP_HOLDER_ABOVE_20_PERCENT")
    if market.liquidity_usd < 10_000:
        risk_score += 15
        reasons.append("LOW_LIQUIDITY")
    if market.volume_24h_usd < 5_000:
        risk_score += 5
        reasons.append("LOW_24H_VOLUME")
    if honeypot:
        risk_score += 40
        reasons.append("SELL_QUOTE_UNAVAILABLE")
    if rugged is True or rugcheck_passed is False:
        risk_score += 50
        reasons.append("RUGCHECK_FAILED")
    if external_risk_score is not None:
        risk_score = max(risk_score, min(100, external_risk_score))

    risk_score = max(0, min(100, risk_score))
    reasons = list(dict.fromkeys(reasons or ["NO_MAJOR_RISK_SIGNAL"]))

    snapshot = (
        db.query(TokenSafetySnapshot)
        .filter(TokenSafetySnapshot.token_mint == token_mint)
        .first()
    )
    if snapshot is None:
        snapshot = TokenSafetySnapshot(token_mint=token_mint)
        db.add(snapshot)

    snapshot.liquidity_usd = market.liquidity_usd
    snapshot.market_cap_usd = market.market_cap_usd
    snapshot.volume_24h_usd = market.volume_24h_usd
    snapshot.top_holder_percent = top_holder_percent
    snapshot.risk_score = risk_score
    snapshot.honeypot = honeypot
    snapshot.mint_authority_enabled = mint_authority_enabled
    snapshot.freeze_authority_enabled = freeze_authority_enabled
    snapshot.rugged = rugged
    snapshot.rugcheck_passed = rugcheck_passed
    snapshot.source = (
        "+".join(successful_sources)
        if not provider_errors
        else "PARTIAL:" + ("+".join(successful_sources) or "NO_PROVIDER")
    )
    snapshot.reasons = reasons
    snapshot.raw_payload = {
        "pair_count": market.pair_count,
        "pairs": market.raw,
        "sell_quote_error": sell_quote_error,
        "rugcheck": rugcheck_report,
        "provider_errors": provider_errors,
        "sell_amount_raw": sell_amount_raw,
        "decimals": decimals,
    }
    snapshot.fetched_at = utc_now()

    db.commit()
    db.refresh(snapshot)
    return snapshot

def get_token_safety_snapshot(
    db: Session,
    *,
    token_mint: str,
    max_age_seconds: int,
    refresh_if_stale: bool = True,
    **refresh_kwargs,
) -> TokenSafetySnapshot | None:
    snapshot = (
        db.query(TokenSafetySnapshot)
        .filter(TokenSafetySnapshot.token_mint == token_mint)
        .first()
    )

    if snapshot is not None:
        fetched_at = ensure_utc(snapshot.fetched_at)
        if fetched_at is not None and fetched_at >= utc_now() - timedelta(seconds=max_age_seconds):
            return snapshot

    if not refresh_if_stale:
        return snapshot

    return refresh_token_safety_snapshot(db, token_mint=token_mint, **refresh_kwargs)


def evaluate_token_safety(
    config: LivePlatformConfig,
    *,
    token_mint: str,
    snapshot: TokenSafetySnapshot | None,
    side: str,
) -> tuple[bool, list[str]]:
    if str(side).upper() == "SELL":
        return True, []

    blocklist = set(config.token_blocklist or [])
    allowlist = set(config.token_allowlist or [])
    reasons: list[str] = []

    if token_mint in blocklist:
        reasons.append("TOKEN_BLOCKLISTED")

    if config.token_allowlist_mode and token_mint not in allowlist:
        reasons.append("TOKEN_NOT_ALLOWLISTED")

    if not config.token_safety_enabled:
        return not reasons, reasons

    if snapshot is None:
        if config.token_safety_fail_closed:
            reasons.append("TOKEN_SAFETY_SNAPSHOT_MISSING")
        return not reasons, reasons

    if snapshot.liquidity_usd < config.min_token_liquidity_usd:
        reasons.append("LIQUIDITY_BELOW_MINIMUM")
    if snapshot.market_cap_usd < config.min_token_market_cap_usd:
        reasons.append("MARKET_CAP_BELOW_MINIMUM")
    if snapshot.volume_24h_usd < config.min_token_volume_24h_usd:
        reasons.append("VOLUME_24H_BELOW_MINIMUM")
    if snapshot.top_holder_percent > config.max_top_holder_percent:
        reasons.append("TOP_HOLDER_ABOVE_MAXIMUM")
    if snapshot.risk_score > config.max_token_risk_score:
        reasons.append("TOKEN_RISK_SCORE_ABOVE_MAXIMUM")
    if config.reject_honeypot and snapshot.honeypot:
        reasons.append("HONEYPOT_REJECTED")
    if config.require_rugcheck_pass and snapshot.rugcheck_passed is not True:
        reasons.append("RUGCHECK_PASS_REQUIRED")
    if config.require_disabled_mint_authority and snapshot.mint_authority_enabled:
        reasons.append("MINT_AUTHORITY_MUST_BE_DISABLED")
    if config.require_disabled_freeze_authority and snapshot.freeze_authority_enabled:
        reasons.append("FREEZE_AUTHORITY_MUST_BE_DISABLED")

    return not reasons, reasons
