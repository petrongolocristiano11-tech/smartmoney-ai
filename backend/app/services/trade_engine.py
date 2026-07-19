from __future__ import annotations

from collections import defaultdict
from decimal import (
    Decimal,
    InvalidOperation,
)

from backend.app.core.constants import (
    SOL_MINT,
)


LAMPORTS_PER_SOL = Decimal(
    "1000000000"
)


def _address(value) -> str:
    return str(
        value or ""
    ).strip()


def _decimal(value) -> Decimal | None:
    if value in (
        None,
        "",
    ):
        return None

    try:
        return Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None


def _positive_float(
    value: Decimal | None,
) -> float | None:
    if value is None or value <= 0:
        return None

    return float(value)


def _raw_token_amount(
    item: dict,
) -> Decimal | None:
    raw = item.get(
        "rawTokenAmount"
    )

    if not isinstance(
        raw,
        dict,
    ):
        return _decimal(
            item.get(
                "tokenAmount"
            )
        )

    amount = _decimal(
        raw.get(
            "tokenAmount"
        )
    )

    if amount is None:
        return None

    try:
        decimals = max(
            0,
            int(
                raw.get(
                    "decimals"
                )
                or 0
            ),
        )

    except (
        TypeError,
        ValueError,
    ):
        decimals = 0

    return amount / (
        Decimal(10)
        ** decimals
    )


def normalize_swap(
    swap: dict,
    wallet_address: str | None = None,
):
    token_transfers = (
        swap.get(
            "tokenTransfers"
        )
        or []
    )

    native_transfers = (
        swap.get(
            "nativeTransfers"
        )
        or []
    )

    account_data = (
        swap.get(
            "accountData"
        )
        or []
    )

    events = (
        swap.get(
            "events"
        )
        or {}
    )

    fee_payer = _address(
        swap.get(
            "feePayer"
        )
    )

    subject_wallet = (
        _address(
            wallet_address
        )
        or fee_payer
    )

    return {
        "signature": swap.get(
            "signature"
        ),
        "timestamp": swap.get(
            "timestamp"
        ),
        "source": swap.get(
            "source"
        ),
        "fee": swap.get(
            "fee"
        ),
        "fee_payer": fee_payer,
        "wallet_address": (
            subject_wallet
        ),
        "transaction_error": (
            swap.get(
                "transactionError"
            )
        ),
        "type": swap.get(
            "type"
        ),
        "description": swap.get(
            "description"
        ),
        "token_transfers": (
            token_transfers
        ),
        "native_transfers": (
            native_transfers
        ),
        "account_data": account_data,
        "events": events,
        "token_transfer_count": len(
            token_transfers
        ),
        "native_transfer_count": len(
            native_transfers
        ),
    }


def extract_swap_tokens(
    normalized_swap: dict,
):
    tokens = []

    for transfer in normalized_swap.get(
        "token_transfers",
        [],
    ):
        if not isinstance(
            transfer,
            dict,
        ):
            continue

        tokens.append(
            {
                "mint": transfer.get(
                    "mint"
                ),
                "amount": transfer.get(
                    "tokenAmount"
                ),
                "from": transfer.get(
                    "fromUserAccount"
                ),
                "to": transfer.get(
                    "toUserAccount"
                ),
            }
        )

    return tokens


def _wallet_token_entries(
    entries,
    wallet: str,
    *,
    direction: str,
) -> list[dict]:
    candidates = []

    for item in entries or []:
        if not isinstance(
            item,
            dict,
        ):
            continue

        user_account = _address(
            item.get(
                "userAccount"
            )
        )

        if (
            user_account
            and user_account != wallet
        ):
            continue

        mint = _address(
            item.get(
                "mint"
            )
        )

        amount = _raw_token_amount(
            item
        )

        if (
            not mint
            or amount is None
            or amount <= 0
        ):
            continue

        candidates.append(
            {
                "mint": mint,
                "amount": amount,
                "direction": direction,
            }
        )

    return candidates


def _largest_token(
    candidates: list[dict],
    *,
    direction: str,
) -> dict | None:
    filtered = [
        item
        for item in candidates
        if (
            item.get(
                "direction"
            )
            == direction
            and item.get(
                "mint"
            )
            != SOL_MINT
            and item.get(
                "amount"
            )
            is not None
            and item[
                "amount"
            ]
            > 0
        )
    ]

    if not filtered:
        return None

    return max(
        filtered,
        key=lambda item: item[
            "amount"
        ],
    )


def _event_swap_analysis(
    normalized_swap: dict,
    wallet: str,
) -> dict | None:
    events = normalized_swap.get(
        "events"
    )

    if not isinstance(
        events,
        dict,
    ):
        return None

    swap_event = events.get(
        "swap"
    )

    if not isinstance(
        swap_event,
        dict,
    ):
        return None

    token_candidates = []

    token_candidates.extend(
        _wallet_token_entries(
            swap_event.get(
                "tokenInputs"
            ),
            wallet,
            direction="OUT",
        )
    )

    token_candidates.extend(
        _wallet_token_entries(
            swap_event.get(
                "tokenOutputs"
            ),
            wallet,
            direction="IN",
        )
    )

    native_input = swap_event.get(
        "nativeInput"
    )

    native_output = swap_event.get(
        "nativeOutput"
    )

    sol_out = None
    sol_in = None

    if isinstance(
        native_input,
        dict,
    ):
        account = _address(
            native_input.get(
                "account"
            )
        )

        amount = _decimal(
            native_input.get(
                "amount"
            )
        )

        if (
            amount is not None
            and amount > 0
            and (
                not account
                or account == wallet
            )
        ):
            sol_out = (
                amount
                / LAMPORTS_PER_SOL
            )

    if isinstance(
        native_output,
        dict,
    ):
        account = _address(
            native_output.get(
                "account"
            )
        )

        amount = _decimal(
            native_output.get(
                "amount"
            )
        )

        if (
            amount is not None
            and amount > 0
            and (
                not account
                or account == wallet
            )
        ):
            sol_in = (
                amount
                / LAMPORTS_PER_SOL
            )

    for item in token_candidates:
        if item[
            "mint"
        ] != SOL_MINT:
            continue

        if item[
            "direction"
        ] == "OUT":
            sol_out = max(
                sol_out or Decimal(0),
                item[
                    "amount"
                ],
            )

        if item[
            "direction"
        ] == "IN":
            sol_in = max(
                sol_in or Decimal(0),
                item[
                    "amount"
                ],
            )

    bought_token = _largest_token(
        token_candidates,
        direction="IN",
    )

    sold_token = _largest_token(
        token_candidates,
        direction="OUT",
    )

    if (
        bought_token is not None
        and sol_out is not None
        and sol_out > 0
    ):
        return {
            "side": "BUY",
            "token_mint": (
                bought_token[
                    "mint"
                ]
            ),
            "token_amount": (
                float(
                    bought_token[
                        "amount"
                    ]
                )
            ),
            "sol_amount": float(
                sol_out
            ),
            "parser": "EVENT_SWAP",
        }

    if (
        sold_token is not None
        and sol_in is not None
        and sol_in > 0
    ):
        return {
            "side": "SELL",
            "token_mint": (
                sold_token[
                    "mint"
                ]
            ),
            "token_amount": (
                float(
                    sold_token[
                        "amount"
                    ]
                )
            ),
            "sol_amount": float(
                sol_in
            ),
            "parser": "EVENT_SWAP",
        }

    return None


def _transfer_swap_analysis(
    normalized_swap: dict,
    wallet: str,
) -> dict | None:
    token_net: dict[
        str,
        Decimal,
    ] = defaultdict(Decimal)

    token_in_max: dict[
        str,
        Decimal,
    ] = defaultdict(Decimal)

    token_out_max: dict[
        str,
        Decimal,
    ] = defaultdict(Decimal)

    for transfer in normalized_swap.get(
        "token_transfers",
        [],
    ):
        if not isinstance(
            transfer,
            dict,
        ):
            continue

        mint = _address(
            transfer.get(
                "mint"
            )
        )

        amount = _decimal(
            transfer.get(
                "tokenAmount"
            )
        )

        if (
            not mint
            or amount is None
            or amount <= 0
        ):
            continue

        from_wallet = _address(
            transfer.get(
                "fromUserAccount"
            )
        )

        to_wallet = _address(
            transfer.get(
                "toUserAccount"
            )
        )

        if from_wallet == wallet:
            token_net[
                mint
            ] -= amount

            token_out_max[
                mint
            ] = max(
                token_out_max[
                    mint
                ],
                amount,
            )

        if to_wallet == wallet:
            token_net[
                mint
            ] += amount

            token_in_max[
                mint
            ] = max(
                token_in_max[
                    mint
                ],
                amount,
            )

    native_out = Decimal(0)
    native_in = Decimal(0)

    for transfer in normalized_swap.get(
        "native_transfers",
        [],
    ):
        if not isinstance(
            transfer,
            dict,
        ):
            continue

        amount = _decimal(
            transfer.get(
                "amount"
            )
        )

        if (
            amount is None
            or amount <= 0
        ):
            continue

        amount_sol = (
            amount
            / LAMPORTS_PER_SOL
        )

        from_wallet = _address(
            transfer.get(
                "fromUserAccount"
            )
        )

        to_wallet = _address(
            transfer.get(
                "toUserAccount"
            )
        )

        if from_wallet == wallet:
            native_out = max(
                native_out,
                amount_sol,
            )

        if to_wallet == wallet:
            native_in = max(
                native_in,
                amount_sol,
            )

    wsol_net = token_net.get(
        SOL_MINT,
        Decimal(0),
    )

    if wsol_net < 0:
        native_out = max(
            native_out,
            abs(
                wsol_net
            ),
            token_out_max.get(
                SOL_MINT,
                Decimal(0),
            ),
        )

    if wsol_net > 0:
        native_in = max(
            native_in,
            wsol_net,
            token_in_max.get(
                SOL_MINT,
                Decimal(0),
            ),
        )

    has_direct_sol_flow = bool(
        native_out > 0
        or native_in > 0
    )

    transaction_type = _address(
        normalized_swap.get(
            "type"
        )
    ).upper()

    if (
        not has_direct_sol_flow
        and transaction_type == "SWAP"
    ):
        for account in normalized_swap.get(
            "account_data",
            [],
        ):
            if not isinstance(
                account,
                dict,
            ):
                continue

            if _address(
                account.get(
                    "account"
                )
            ) != wallet:
                continue

            native_change = _decimal(
                account.get(
                    "nativeBalanceChange"
                )
            )

            if native_change is None:
                continue

            native_change_sol = (
                native_change
                / LAMPORTS_PER_SOL
            )

            if native_change_sol < 0:
                native_out = max(
                    native_out,
                    abs(
                        native_change_sol
                    ),
                )

            if native_change_sol > 0:
                native_in = max(
                    native_in,
                    native_change_sol,
                )

    for account in normalized_swap.get(
        "account_data",
        [],
    ):
        if not isinstance(
            account,
            dict,
        ):
            continue

        for change in account.get(
            "tokenBalanceChanges"
        ) or []:
            if not isinstance(
                change,
                dict,
            ):
                continue

            if _address(
                change.get(
                    "userAccount"
                )
            ) != wallet:
                continue

            mint = _address(
                change.get(
                    "mint"
                )
            )

            if not mint:
                continue

            if token_net.get(
                mint,
                Decimal(0),
            ) != 0:
                continue

            amount = _raw_token_amount(
                change
            )

            if (
                amount is None
                or amount == 0
            ):
                continue

            token_net[
                mint
            ] += amount

    bought_candidates = [
        {
            "mint": mint,
            "amount": amount,
        }
        for mint, amount in (
            token_net.items()
        )
        if (
            mint != SOL_MINT
            and amount > 0
        )
    ]

    sold_candidates = [
        {
            "mint": mint,
            "amount": abs(
                amount
            ),
        }
        for mint, amount in (
            token_net.items()
        )
        if (
            mint != SOL_MINT
            and amount < 0
        )
    ]

    bought_token = (
        max(
            bought_candidates,
            key=lambda item: item[
                "amount"
            ],
        )
        if bought_candidates
        else None
    )

    sold_token = (
        max(
            sold_candidates,
            key=lambda item: item[
                "amount"
            ],
        )
        if sold_candidates
        else None
    )

    if (
        bought_token is not None
        and native_out > 0
    ):
        return {
            "side": "BUY",
            "token_mint": (
                bought_token[
                    "mint"
                ]
            ),
            "token_amount": float(
                bought_token[
                    "amount"
                ]
            ),
            "sol_amount": float(
                native_out
            ),
            "parser": (
                "TRANSFER_FLOW"
            ),
        }

    if (
        sold_token is not None
        and native_in > 0
    ):
        return {
            "side": "SELL",
            "token_mint": (
                sold_token[
                    "mint"
                ]
            ),
            "token_amount": float(
                sold_token[
                    "amount"
                ]
            ),
            "sol_amount": float(
                native_in
            ),
            "parser": (
                "TRANSFER_FLOW"
            ),
        }

    return None


def analyze_swap(
    normalized_swap: dict,
) -> dict:
    wallet = (
        _address(
            normalized_swap.get(
                "wallet_address"
            )
        )
        or _address(
            normalized_swap.get(
                "fee_payer"
            )
        )
    )

    empty = {
        "side": "UNKNOWN",
        "token_mint": None,
        "token_amount": None,
        "sol_amount": None,
        "parser": None,
    }

    if not wallet:
        return empty

    if normalized_swap.get(
        "transaction_error"
    ):
        return empty

    event_analysis = (
        _event_swap_analysis(
            normalized_swap,
            wallet,
        )
    )

    if event_analysis is not None:
        return event_analysis

    transfer_analysis = (
        _transfer_swap_analysis(
            normalized_swap,
            wallet,
        )
    )

    return (
        transfer_analysis
        or empty
    )


def identify_swap_side(
    normalized_swap: dict,
):
    return analyze_swap(
        normalized_swap
    )[
        "side"
    ]


def extract_trade_amounts(
    normalized_swap: dict,
):
    analysis = analyze_swap(
        normalized_swap
    )

    return {
        "token_mint": analysis[
            "token_mint"
        ],
        "token_amount": analysis[
            "token_amount"
        ],
        "sol_amount": analysis[
            "sol_amount"
        ],
    }


def summarize_swap(
    normalized_swap: dict,
):
    tokens = extract_swap_tokens(
        normalized_swap
    )

    return {
        "signature": normalized_swap[
            "signature"
        ],
        "timestamp": normalized_swap[
            "timestamp"
        ],
        "source": normalized_swap[
            "source"
        ],
        "fee_payer": normalized_swap[
            "fee_payer"
        ],
        "wallet_address": (
            normalized_swap.get(
                "wallet_address"
            )
        ),
        "token_count": len(
            tokens
        ),
        "tokens": tokens,
    }


def build_trade(
    normalized_swap: dict,
):
    summary = summarize_swap(
        normalized_swap
    )

    analysis = analyze_swap(
        normalized_swap
    )

    return {
        "signature": summary[
            "signature"
        ],
        "timestamp": summary[
            "timestamp"
        ],
        "source": summary[
            "source"
        ],
        "fee_payer": summary[
            "fee_payer"
        ],
        "wallet_address": summary[
            "wallet_address"
        ],
        "side": analysis[
            "side"
        ],
        "tokens": summary[
            "tokens"
        ],
        "token_count": summary[
            "token_count"
        ],
        "token_mint": analysis[
            "token_mint"
        ],
        "token_amount": analysis[
            "token_amount"
        ],
        "sol_amount": analysis[
            "sol_amount"
        ],
        "parser": analysis[
            "parser"
        ],
        "fee": normalized_swap[
            "fee"
        ],
    }


def build_trade_data(
    wallet: str,
    trade: dict,
):
    return {
        "signature": trade[
            "signature"
        ],
        "wallet_address": wallet,
        "side": trade[
            "side"
        ],
        "source": trade[
            "source"
        ],
        "token_mint": trade[
            "token_mint"
        ],
        "token_amount": trade[
            "token_amount"
        ],
        "sol_amount": trade[
            "sol_amount"
        ],
        "fee": trade[
            "fee"
        ],
        "success": True,
        "block_time": None,
        "raw_json": str(
            trade
        ),
    }
