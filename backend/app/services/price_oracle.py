from dataclasses import dataclass
from datetime import (
    datetime,
    timezone,
)
from math import isfinite
from threading import RLock
from time import monotonic
from typing import (
    Any,
    Iterable,
)

import httpx

from backend.app.core.config import (
    settings,
)


SOL_MINT = (
    "So11111111111111111111111111111111111111112"
)

MAX_IDS_PER_REQUEST = 50

PRICE_SOURCE = "JUPITER_PRICE_V3"


class PriceOracleError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "PRICE_ORACLE_ERROR",
    ):
        super().__init__(message)

        self.message = message
        self.code = code


@dataclass(frozen=True)
class OraclePrice:
    token_mint: str

    usd_price: float
    sol_price: float
    sol_usd_price: float

    block_id: int | None
    decimals: int | None

    price_change_24h: float | None

    fetched_at: datetime
    source: str = PRICE_SOURCE

    def as_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "token_mint": self.token_mint,
            "usd_price": self.usd_price,
            "sol_price": self.sol_price,
            "sol_usd_price": (
                self.sol_usd_price
            ),
            "block_id": self.block_id,
            "decimals": self.decimals,
            "price_change_24h": (
                self.price_change_24h
            ),
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


@dataclass(frozen=True)
class OracleBatch:
    prices: dict[
        str,
        OraclePrice,
    ]

    missing_token_mints: list[str]

    fetched_at: datetime


class JupiterPriceOracle:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: (
            float | None
        ) = None,
        cache_ttl_seconds: (
            int | None
        ) = None,
        transport: (
            httpx.BaseTransport | None
        ) = None,
    ):
        self.api_key = str(
            api_key
            if api_key is not None
            else settings.JUPITER_API_KEY
        ).strip()

        self.base_url = str(
            base_url
            or settings
            .JUPITER_PRICE_API_URL
        ).strip().rstrip("/")

        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else settings
            .JUPITER_PRICE_TIMEOUT_SECONDS
        )

        self.cache_ttl_seconds = int(
            cache_ttl_seconds
            if cache_ttl_seconds is not None
            else settings
            .JUPITER_PRICE_CACHE_SECONDS
        )

        self.transport = transport

        self._cache: dict[
            str,
            tuple[
                float,
                OraclePrice,
            ],
        ] = {}

        self._missing_cache: dict[
            str,
            float,
        ] = {}

        self._lock = RLock()

    @staticmethod
    def _normalize_token_mints(
        token_mints: Iterable[str],
    ) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for value in token_mints:
            mint = str(
                value or ""
            ).strip()

            if not mint:
                continue

            if len(mint) > 64:
                raise PriceOracleError(
                    "Il token mint supera "
                    "la lunghezza consentita.",
                    code="INVALID_TOKEN_MINT",
                )

            if mint not in seen:
                seen.add(mint)
                normalized.append(mint)

        if not normalized:
            raise PriceOracleError(
                "Specificare almeno "
                "un token mint.",
                code="EMPTY_PRICE_REQUEST",
            )

        return normalized

    @staticmethod
    def _positive_float(
        value: Any,
        field_name: str,
    ) -> float:
        try:
            normalized = float(value)
        except (
            TypeError,
            ValueError,
        ) as exception:
            raise PriceOracleError(
                "Risposta Jupiter non "
                f"valida: {field_name}.",
                code=(
                    "INVALID_ORACLE_RESPONSE"
                ),
            ) from exception

        if (
            not isfinite(normalized)
            or normalized <= 0
        ):
            raise PriceOracleError(
                "Risposta Jupiter non "
                f"valida: {field_name}.",
                code=(
                    "INVALID_ORACLE_RESPONSE"
                ),
            )

        return normalized

    def clear_cache(
        self,
    ) -> None:
        with self._lock:
            self._cache.clear()
            self._missing_cache.clear()

    def _read_cache(
        self,
        token_mint: str,
        now_monotonic: float,
    ) -> tuple[
        OraclePrice | None,
        bool,
    ]:
        with self._lock:
            cached = self._cache.get(
                token_mint
            )

            if cached is not None:
                expires_at, quote = cached

                if expires_at > now_monotonic:
                    return quote, False

                self._cache.pop(
                    token_mint,
                    None,
                )

            missing_expires_at = (
                self._missing_cache.get(
                    token_mint
                )
            )

            if (
                missing_expires_at
                is not None
                and missing_expires_at
                > now_monotonic
            ):
                return None, True

            self._missing_cache.pop(
                token_mint,
                None,
            )

        return None, False

    def _store_quotes(
        self,
        quotes: dict[
            str,
            OraclePrice,
        ],
        missing: list[str],
        now_monotonic: float,
    ) -> None:
        expires_at = (
            now_monotonic
            + self.cache_ttl_seconds
        )

        with self._lock:
            for mint, quote in (
                quotes.items()
            ):
                self._cache[mint] = (
                    expires_at,
                    quote,
                )

                self._missing_cache.pop(
                    mint,
                    None,
                )

            for mint in missing:
                self._missing_cache[
                    mint
                ] = expires_at

                self._cache.pop(
                    mint,
                    None,
                )

    def _request_prices(
        self,
        token_mints: list[str],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise PriceOracleError(
                "Jupiter Price API "
                "non configurata.",
                code=(
                    "ORACLE_NOT_CONFIGURED"
                ),
            )

        try:
            with httpx.Client(
                timeout=(
                    self.timeout_seconds
                ),
                transport=self.transport,
            ) as client:
                response = client.get(
                    self.base_url,
                    params={
                        "ids": ",".join(
                            token_mints
                        ),
                    },
                    headers={
                        "Accept": (
                            "application/json"
                        ),
                        "x-api-key": (
                            self.api_key
                        ),
                        "User-Agent": (
                            "SmartMoney-AI/1.0"
                        ),
                    },
                )

        except (
            httpx.TimeoutException
        ) as exception:
            raise PriceOracleError(
                "Jupiter Price API non "
                "ha risposto in tempo.",
                code="ORACLE_TIMEOUT",
            ) from exception

        except (
            httpx.HTTPError
        ) as exception:
            raise PriceOracleError(
                "Jupiter Price API "
                "non raggiungibile.",
                code="ORACLE_UNAVAILABLE",
            ) from exception

        if response.status_code in {
            401,
            403,
        }:
            raise PriceOracleError(
                "Chiave Jupiter rifiutata.",
                code=(
                    "ORACLE_"
                    "AUTHENTICATION_FAILED"
                ),
            )

        if response.status_code == 429:
            raise PriceOracleError(
                "Limite richieste Jupiter "
                "raggiunto.",
                code=(
                    "ORACLE_RATE_LIMITED"
                ),
            )

        if response.status_code >= 500:
            raise PriceOracleError(
                "Jupiter Price API "
                "temporaneamente non "
                "disponibile.",
                code="ORACLE_UNAVAILABLE",
            )

        if not response.is_success:
            raise PriceOracleError(
                "Jupiter Price API ha "
                "restituito HTTP "
                f"{response.status_code}.",
                code=(
                    "ORACLE_REQUEST_REJECTED"
                ),
            )

        try:
            payload = response.json()
        except ValueError as exception:
            raise PriceOracleError(
                "Jupiter Price API ha "
                "restituito JSON non valido.",
                code=(
                    "INVALID_ORACLE_RESPONSE"
                ),
            ) from exception

        if not isinstance(
            payload,
            dict,
        ):
            raise PriceOracleError(
                "Jupiter Price API ha "
                "restituito un formato "
                "non valido.",
                code=(
                    "INVALID_ORACLE_RESPONSE"
                ),
            )

        return payload

    def _fetch_uncached(
        self,
        token_mints: list[str],
    ) -> OracleBatch:
        requested_without_sol = [
            mint
            for mint in token_mints
            if mint != SOL_MINT
        ]

        first_chunk = (
            requested_without_sol[
                : MAX_IDS_PER_REQUEST - 1
            ]
            + [SOL_MINT]
        )

        chunks: list[
            list[str]
        ] = [first_chunk]

        remaining = (
            requested_without_sol[
                MAX_IDS_PER_REQUEST - 1 :
            ]
        )

        for index in range(
            0,
            len(remaining),
            MAX_IDS_PER_REQUEST,
        ):
            chunks.append(
                remaining[
                    index :
                    index
                    + MAX_IDS_PER_REQUEST
                ]
            )

        raw_prices: dict[
            str,
            Any,
        ] = {}

        for chunk in chunks:
            if chunk:
                raw_prices.update(
                    self._request_prices(
                        chunk
                    )
                )

        sol_payload = raw_prices.get(
            SOL_MINT
        )

        if not isinstance(
            sol_payload,
            dict,
        ):
            raise PriceOracleError(
                "Prezzo SOL non "
                "disponibile.",
                code=(
                    "SOL_PRICE_NOT_AVAILABLE"
                ),
            )

        sol_usd_price = (
            self._positive_float(
                sol_payload.get(
                    "usdPrice"
                ),
                "SOL usdPrice",
            )
        )

        fetched_at = datetime.now(
            timezone.utc
        )

        quotes: dict[
            str,
            OraclePrice,
        ] = {}

        missing: list[str] = []

        for mint in token_mints:
            payload = raw_prices.get(mint)

            if not isinstance(
                payload,
                dict,
            ):
                missing.append(mint)
                continue

            usd_price = (
                self._positive_float(
                    payload.get(
                        "usdPrice"
                    ),
                    f"{mint} usdPrice",
                )
            )

            block_id_value = payload.get(
                "blockId"
            )

            decimals_value = payload.get(
                "decimals"
            )

            change_value = payload.get(
                "priceChange24h"
            )

            try:
                block_id = (
                    int(block_id_value)
                    if block_id_value
                    is not None
                    else None
                )
            except (
                TypeError,
                ValueError,
            ):
                block_id = None

            try:
                decimals = (
                    int(decimals_value)
                    if decimals_value
                    is not None
                    else None
                )
            except (
                TypeError,
                ValueError,
            ):
                decimals = None

            try:
                price_change_24h = (
                    float(change_value)
                    if change_value
                    is not None
                    else None
                )

                if (
                    price_change_24h
                    is not None
                    and not isfinite(
                        price_change_24h
                    )
                ):
                    price_change_24h = None

            except (
                TypeError,
                ValueError,
            ):
                price_change_24h = None

            quotes[mint] = OraclePrice(
                token_mint=mint,
                usd_price=usd_price,
                sol_price=(
                    usd_price
                    / sol_usd_price
                ),
                sol_usd_price=(
                    sol_usd_price
                ),
                block_id=block_id,
                decimals=decimals,
                price_change_24h=(
                    price_change_24h
                ),
                fetched_at=fetched_at,
            )

        return OracleBatch(
            prices=quotes,
            missing_token_mints=missing,
            fetched_at=fetched_at,
        )

    def get_prices(
        self,
        token_mints: Iterable[str],
        force_refresh: bool = False,
    ) -> OracleBatch:
        normalized = (
            self._normalize_token_mints(
                token_mints
            )
        )

        now_monotonic = monotonic()

        prices: dict[
            str,
            OraclePrice,
        ] = {}

        missing: list[str] = []
        unresolved: list[str] = []

        for mint in normalized:
            if force_refresh:
                unresolved.append(mint)
                continue

            quote, is_missing = (
                self._read_cache(
                    mint,
                    now_monotonic,
                )
            )

            if quote is not None:
                prices[mint] = quote

            elif is_missing:
                missing.append(mint)

            else:
                unresolved.append(mint)

        fetched_at = datetime.now(
            timezone.utc
        )

        if unresolved:
            fresh = self._fetch_uncached(
                unresolved
            )

            prices.update(fresh.prices)

            missing.extend(
                fresh.missing_token_mints
            )

            fetched_at = fresh.fetched_at

            self._store_quotes(
                fresh.prices,
                fresh.missing_token_mints,
                now_monotonic,
            )

        missing_set = set(missing)

        ordered_missing = [
            mint
            for mint in normalized
            if mint in missing_set
        ]

        return OracleBatch(
            prices={
                mint: prices[mint]
                for mint in normalized
                if mint in prices
            },
            missing_token_mints=(
                ordered_missing
            ),
            fetched_at=fetched_at,
        )

    def get_price(
        self,
        token_mint: str,
        force_refresh: bool = False,
    ) -> OraclePrice:
        normalized = (
            self._normalize_token_mints(
                [token_mint]
            )[0]
        )

        batch = self.get_prices(
            [normalized],
            force_refresh=force_refresh,
        )

        quote = batch.prices.get(
            normalized
        )

        if quote is None:
            raise PriceOracleError(
                "Jupiter non ha restituito "
                "un prezzo affidabile per "
                "questo token.",
                code=(
                    "PRICE_NOT_AVAILABLE"
                ),
            )

        return quote


_default_price_oracle = (
    JupiterPriceOracle()
)


def get_price_oracle(
) -> JupiterPriceOracle:
    return _default_price_oracle 