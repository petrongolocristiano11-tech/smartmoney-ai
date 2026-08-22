from __future__ import annotations

import math
import struct
import time
from typing import Any

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
BUY_EXACT_SOL_IN_DISCRIMINATOR = bytes([56, 252, 116, 8, 158, 223, 205, 95])
EVENT_CPI_DISCRIMINATOR = bytes([228, 69, 165, 46, 81, 203, 154, 29])
TRADE_EVENT_DISCRIMINATOR = bytes([189, 219, 127, 211, 78, 230, 97, 238])
LAMPORTS_PER_SOL = 1_000_000_000

_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_MAP = {value: index for index, value in enumerate(_BASE58)}


def _b58decode(value: str) -> bytes | None:
    try:
        number = 0
        for char in value:
            number = number * 58 + _BASE58_MAP[char]
        raw = (
            b""
            if number == 0
            else number.to_bytes((number.bit_length() + 7) // 8, "big")
        )
        zeroes = 0
        for char in value:
            if char != "1":
                break
            zeroes += 1
        return (b"\x00" * zeroes) + raw
    except Exception:
        return None


def _b58encode(raw: bytes) -> str:
    number = int.from_bytes(raw, "big")
    chars: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        chars.append(_BASE58[remainder])
    zeroes = 0
    for value in raw:
        if value != 0:
            break
        zeroes += 1
    return ("1" * zeroes) + ("".join(reversed(chars)) if chars else "")


def _ceil_div(value: int, denominator: int) -> int:
    if denominator <= 0:
        raise ValueError("PUMP_SHADOW_NONPOSITIVE_DENOMINATOR")
    return (value + denominator - 1) // denominator


def _calc_net_lamports(
    spendable_lamports: int,
    protocol_fee_bps: int,
    secondary_fee_bps: int,
) -> int:
    spendable = int(spendable_lamports)
    protocol = max(0, int(protocol_fee_bps))
    secondary = max(0, int(secondary_fee_bps))
    if spendable <= 0:
        return 0
    total_fee_bps = protocol + secondary
    net = spendable * 10_000 // (10_000 + total_fee_bps)
    fees = (
        _ceil_div(net * protocol, 10_000)
        + _ceil_div(net * secondary, 10_000)
    )
    if net + fees > spendable:
        net -= (net + fees - spendable)
    return max(0, net)


def _infer_secondary_fee_bps(
    *,
    spendable_lamports: int,
    curve_net_lamports: int,
    protocol_fee_bps: int,
    maximum_secondary_bps: int = 1_000,
) -> int | None:
    matches = [
        secondary
        for secondary in range(max(0, int(maximum_secondary_bps)) + 1)
        if _calc_net_lamports(
            int(spendable_lamports),
            int(protocol_fee_bps),
            secondary,
        )
        == int(curve_net_lamports)
    ]
    if len(matches) != 1:
        return None
    return int(matches[0])


def _quote_tokens_out(
    *,
    net_lamports: int,
    virtual_token_reserves: int,
    virtual_sol_reserves: int,
) -> int:
    net = int(net_lamports)
    token_reserves = int(virtual_token_reserves)
    sol_reserves = int(virtual_sol_reserves)
    if net <= 1 or token_reserves <= 0 or sol_reserves <= 0:
        return 0
    return (net - 1) * token_reserves // (sol_reserves + net - 1)


def _account_keys(payload: dict[str, Any]) -> list[str]:
    transaction = payload.get("transaction")
    message = transaction.get("message") if isinstance(transaction, dict) else None
    keys: list[str] = []
    if isinstance(message, dict):
        for item in message.get("accountKeys") or []:
            value = item.get("pubkey") if isinstance(item, dict) else item
            text = str(value or "").strip()
            if text:
                keys.append(text)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    loaded = meta.get("loadedAddresses") if isinstance(meta, dict) else None
    if isinstance(loaded, dict):
        for group in ("writable", "readonly"):
            for value in loaded.get(group) or []:
                text = str(value or "").strip()
                if text:
                    keys.append(text)
    return keys


def _program_id(instruction: Any, keys: list[str]) -> str | None:
    if not isinstance(instruction, dict):
        return None
    direct = instruction.get("programId")
    if direct:
        return str(direct)
    try:
        index = int(instruction.get("programIdIndex"))
    except (TypeError, ValueError):
        return None
    if 0 <= index < len(keys):
        return keys[index]
    return None


def _resolve_accounts(instruction: Any, keys: list[str]) -> list[str]:
    if not isinstance(instruction, dict):
        return []
    out: list[str] = []
    for item in instruction.get("accounts") or []:
        if isinstance(item, str):
            out.append(item)
            continue
        if isinstance(item, dict):
            value = item.get("pubkey")
            if value:
                out.append(str(value))
            continue
        try:
            index = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(keys):
            out.append(keys[index])
    return out


def _outer_instructions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keys = _account_keys(payload)
    transaction = payload.get("transaction")
    message = transaction.get("message") if isinstance(transaction, dict) else None
    if not isinstance(message, dict):
        return []
    out: list[dict[str, Any]] = []
    for position, instruction in enumerate(message.get("instructions") or []):
        if not isinstance(instruction, dict):
            continue
        out.append(
            {
                "position": position,
                "program_id": _program_id(instruction, keys),
                "accounts": _resolve_accounts(instruction, keys),
                "data": _b58decode(str(instruction.get("data") or "")),
            }
        )
    return out


def _inner_instructions_for_outer(
    payload: dict[str, Any],
    outer_position: int,
) -> list[dict[str, Any]]:
    keys = _account_keys(payload)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    out: list[dict[str, Any]] = []
    for group in meta.get("innerInstructions") or []:
        if not isinstance(group, dict):
            continue
        try:
            index = int(group.get("index"))
        except (TypeError, ValueError):
            continue
        if index != int(outer_position):
            continue
        for position, instruction in enumerate(group.get("instructions") or []):
            if not isinstance(instruction, dict):
                continue
            out.append(
                {
                    "position": position,
                    "program_id": _program_id(instruction, keys),
                    "accounts": _resolve_accounts(instruction, keys),
                    "data": _b58decode(str(instruction.get("data") or "")),
                }
            )
    return out


class _Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def _take(self, count: int) -> bytes:
        if count < 0 or self.position + count > len(self.data):
            raise ValueError("PUMP_SHADOW_TRADE_EVENT_TRUNCATED")
        value = self.data[self.position : self.position + count]
        self.position += count
        return value

    def u8(self) -> int:
        return self._take(1)[0]

    def boolean(self) -> bool:
        value = self.u8()
        if value not in (0, 1):
            raise ValueError("PUMP_SHADOW_INVALID_BOOL")
        return bool(value)

    def u64(self) -> int:
        return struct.unpack("<Q", self._take(8))[0]

    def i64(self) -> int:
        return struct.unpack("<q", self._take(8))[0]

    def pubkey(self) -> str:
        return _b58encode(self._take(32))


def _decode_trade_event_prefix(raw: bytes) -> dict[str, Any]:
    prefix = EVENT_CPI_DISCRIMINATOR + TRADE_EVENT_DISCRIMINATOR
    if not raw.startswith(prefix):
        raise ValueError("PUMP_SHADOW_NOT_TRADE_EVENT")
    reader = _Reader(raw[len(prefix) :])
    return {
        "mint": reader.pubkey(),
        "sol_amount": reader.u64(),
        "token_amount": reader.u64(),
        "is_buy": reader.boolean(),
        "user": reader.pubkey(),
        "timestamp": reader.i64(),
        "virtual_sol_reserves": reader.u64(),
        "virtual_token_reserves": reader.u64(),
        "real_sol_reserves": reader.u64(),
        "real_token_reserves": reader.u64(),
        "fee_recipient": reader.pubkey(),
        "fee_basis_points": reader.u64(),
        "fee": reader.u64(),
        "creator": reader.pubkey(),
        "creator_fee_basis_points": reader.u64(),
        "creator_fee": reader.u64(),
    }


def _unavailable(reason: str, *, latency_ms: float, **evidence: Any) -> dict[str, Any]:
    return {
        "version": "m132-pump-event-local-quote-shadow/1",
        "available": False,
        "reason": str(reason),
        "quote_latency_ms": round(max(0.0, float(latency_ms)), 6),
        "provider_api_calls": 0,
        "rpc_reads": 0,
        "transaction_built": False,
        "canonical_acceptance_mutated": False,
        "live_execution": False,
        "signer_access": False,
        **evidence,
    }


def quote_pump_buy_exact_sol_in_shadow(
    payload: dict[str, Any],
    *,
    wallet_address: str,
    token_mint: str,
    token_decimals: int,
    wallet_effective_price_sol: float | None,
    simulated_input_lamports: int,
    slippage_bps: int,
) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        wallet = str(wallet_address or "").strip()
        mint = str(token_mint or "").strip()
        decimals = int(token_decimals)
        copy_input = int(simulated_input_lamports)
        slippage = int(slippage_bps)
        if not wallet or not mint or decimals < 0 or copy_input <= 0:
            return _unavailable(
                "INVALID_SIGNAL_INPUT",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )
        if slippage < 0 or slippage > 10_000:
            return _unavailable(
                "INVALID_SLIPPAGE",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        outers = _outer_instructions(payload)
        direct: list[dict[str, Any]] = []
        for instruction in outers:
            raw = instruction.get("data")
            accounts = instruction.get("accounts") or []
            if (
                instruction.get("program_id") == PUMP_PROGRAM_ID
                and isinstance(raw, bytes)
                and raw.startswith(BUY_EXACT_SOL_IN_DISCRIMINATOR)
                and wallet in accounts
                and mint in accounts
            ):
                direct.append(instruction)

        if len(direct) != 1:
            return _unavailable(
                f"DIRECT_BUY_EXACT_SOL_IN_COUNT_{len(direct)}",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        target = direct[0]
        raw = target.get("data")
        accounts = list(target.get("accounts") or [])
        if not isinstance(raw, bytes) or len(raw) != 25:
            return _unavailable(
                "UNSUPPORTED_BUY_EXACT_SOL_IN_DATA",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )
        if len(accounts) != 18:
            return _unavailable(
                f"UNSUPPORTED_ACCOUNT_COUNT_{len(accounts)}",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )
        if accounts[2] != mint or accounts[6] != wallet:
            return _unavailable(
                "ACCOUNT_LAYOUT_SIGNAL_MISMATCH",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        target_spendable = struct.unpack("<Q", raw[8:16])[0]
        target_min_tokens_out = struct.unpack("<Q", raw[16:24])[0]

        later_same_mint = any(
            int(instruction.get("position") or 0) > int(target["position"])
            and instruction.get("program_id") == PUMP_PROGRAM_ID
            and mint in (instruction.get("accounts") or [])
            for instruction in outers
        )
        if later_same_mint:
            return _unavailable(
                "LATER_SAME_MINT_PUMP_INSTRUCTION",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
                target_spendable_lamports=int(target_spendable),
            )

        events: list[dict[str, Any]] = []
        for instruction in _inner_instructions_for_outer(
            payload,
            int(target["position"]),
        ):
            event_raw = instruction.get("data")
            if (
                instruction.get("program_id") != PUMP_PROGRAM_ID
                or not isinstance(event_raw, bytes)
                or not event_raw.startswith(
                    EVENT_CPI_DISCRIMINATOR + TRADE_EVENT_DISCRIMINATOR
                )
            ):
                continue
            event = _decode_trade_event_prefix(event_raw)
            if (
                event["user"] == wallet
                and event["mint"] == mint
                and bool(event["is_buy"])
            ):
                events.append(event)

        if len(events) != 1:
            return _unavailable(
                f"MATCHING_TRADE_EVENT_COUNT_{len(events)}",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        event = events[0]
        if int(event["token_amount"]) <= 0:
            return _unavailable(
                "EVENT_TOKEN_AMOUNT_NONPOSITIVE",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        protocol_bps = int(event["fee_basis_points"])
        inferred_secondary_bps = _infer_secondary_fee_bps(
            spendable_lamports=int(target_spendable),
            curve_net_lamports=int(event["sol_amount"]),
            protocol_fee_bps=protocol_bps,
        )
        if inferred_secondary_bps is None:
            return _unavailable(
                "SECONDARY_FEE_BPS_NOT_UNIQUELY_INFERRED",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
                protocol_fee_bps=protocol_bps,
                creator_fee_basis_points=int(event["creator_fee_basis_points"]),
            )

        # Cross-validate that the TradeEvent reserves are post-trade for the
        # exact target instruction before using them as the starting state for
        # the local copy quote.
        target_curve_net = _calc_net_lamports(
            int(target_spendable),
            protocol_bps,
            inferred_secondary_bps,
        )
        if target_curve_net != int(event["sol_amount"]):
            return _unavailable(
                "TARGET_CURVE_NET_MISMATCH",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )
        pre_virtual_sol = int(event["virtual_sol_reserves"]) - target_curve_net
        pre_virtual_token = (
            int(event["virtual_token_reserves"]) + int(event["token_amount"])
        )
        target_replayed = _quote_tokens_out(
            net_lamports=target_curve_net,
            virtual_token_reserves=pre_virtual_token,
            virtual_sol_reserves=pre_virtual_sol,
        )
        if target_replayed != int(event["token_amount"]):
            return _unavailable(
                "POST_TRADE_STATE_CROSS_VALIDATION_FAILED",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )

        copy_curve_net = _calc_net_lamports(
            copy_input,
            protocol_bps,
            inferred_secondary_bps,
        )
        expected_out = _quote_tokens_out(
            net_lamports=copy_curve_net,
            virtual_token_reserves=int(event["virtual_token_reserves"]),
            virtual_sol_reserves=int(event["virtual_sol_reserves"]),
        )
        if expected_out <= 0:
            return _unavailable(
                "NO_EXECUTABLE_OUTPUT",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
            )
        if expected_out > int(event["real_token_reserves"]):
            return _unavailable(
                "INSUFFICIENT_REAL_TOKEN_RESERVES",
                latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
                expected_out_raw=int(expected_out),
                real_token_reserves=int(event["real_token_reserves"]),
            )

        conservative_out = (
            int(expected_out) * max(0, 10_000 - slippage) // 10_000
        )
        deterioration_bps: float | None = None
        if (
            wallet_effective_price_sol is not None
            and float(wallet_effective_price_sol) > 0
            and conservative_out > 0
        ):
            token_units = conservative_out / (10 ** decimals)
            if token_units > 0:
                bot_price = (copy_input / LAMPORTS_PER_SOL) / token_units
                deterioration_bps = (
                    (bot_price / float(wallet_effective_price_sol)) - 1.0
                ) * 10_000.0

        curve_impact_bps: float | None = None
        post_vsol = int(event["virtual_sol_reserves"])
        post_vtoken = int(event["virtual_token_reserves"])
        if copy_curve_net > 1 and post_vsol > 0 and post_vtoken > 0:
            ideal_out = (copy_curve_net - 1) * post_vtoken / post_vsol
            if ideal_out > 0:
                curve_impact_bps = max(
                    0.0,
                    (1.0 - (expected_out / ideal_out)) * 10_000.0,
                )

        pam_pass = bool(
            deterioration_bps is not None and deterioration_bps <= 1_000.0
        )
        diagnostic_impact_pass = bool(
            curve_impact_bps is not None and curve_impact_bps <= 500.0
        )
        latency_ms = (time.perf_counter_ns() - started) / 1_000_000
        return {
            "version": "m132-pump-event-local-quote-shadow/1",
            "available": True,
            "reason": None,
            "source": "TARGET_TRADE_EVENT_POST_STATE",
            "quote_latency_ms": round(max(0.0, latency_ms), 6),
            "provider_api_calls": 0,
            "rpc_reads": 0,
            "transaction_built": False,
            "canonical_acceptance_mutated": False,
            "live_execution": False,
            "signer_access": False,
            "target_spendable_lamports": int(target_spendable),
            "target_min_tokens_out_raw": int(target_min_tokens_out),
            "target_curve_net_lamports": int(target_curve_net),
            "protocol_fee_bps": protocol_bps,
            "event_creator_fee_bps": int(event["creator_fee_basis_points"]),
            "inferred_secondary_fee_bps": int(inferred_secondary_bps),
            "secondary_fee_interpretation": (
                "CREATOR_FEE"
                if int(event["creator_fee_basis_points"])
                == int(inferred_secondary_bps)
                else "REDIRECTED_OR_CASHBACK_FEE"
            ),
            "copy_input_lamports": copy_input,
            "copy_curve_net_lamports": int(copy_curve_net),
            "expected_out_raw": int(expected_out),
            "conservative_out_raw": int(conservative_out),
            "price_deterioration_bps": deterioration_bps,
            "diagnostic_curve_impact_bps": curve_impact_bps,
            "pam_limit_bps": 1_000,
            "diagnostic_impact_limit_bps": 500,
            "pam_pass": pam_pass,
            "diagnostic_impact_pass": diagnostic_impact_pass,
            "diagnostic_quote_pass": bool(
                pam_pass and diagnostic_impact_pass and conservative_out > 0
            ),
            "historical_model_contract": (
                "TARGET_EVENT_SOL_AMOUNT_MUST_MATCH_PROTOCOL_PLUS_UNIQUE_SECONDARY_FEE"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return _unavailable(
            f"INTERNAL_{type(exc).__name__}",
            latency_ms=(time.perf_counter_ns() - started) / 1_000_000,
        )
