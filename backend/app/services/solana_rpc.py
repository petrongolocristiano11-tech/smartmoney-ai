from typing import Any

import httpx

from backend.app.core.config import settings
from backend.app.services.raw_blockchain_capture_service import (
    RawCaptureContext,
    capture_raw_blockchain_payload_safely,
)
from backend.app.services.live_trading_errors import (
    SolanaRpcError,
)


LAMPORTS_PER_SOL = 1_000_000_000


def _rpc_capture_context(
    method: str,
    params: list,
    body: dict,
) -> RawCaptureContext:
    observed_wallet: str | None = None
    transaction_signature: str | None = None
    commitment: str | None = None
    slot: int | None = None
    block_time: int | float | None = None

    wallet_methods = {
        "getBalance",
        "getSignaturesForAddress",
        "getTokenAccountsByOwner",
        "getTokenAccountBalance",
    }
    if method in wallet_methods and params and isinstance(params[0], str):
        observed_wallet = params[0]

    if method == "getTransaction" and params and isinstance(params[0], str):
        transaction_signature = params[0]
    elif method == "getSignatureStatuses" and params:
        signatures = params[0]
        if isinstance(signatures, list) and signatures:
            transaction_signature = str(signatures[0])

    for item in params:
        if isinstance(item, dict) and item.get("commitment"):
            commitment = str(item["commitment"])
            break

    result = body.get("result")
    if isinstance(result, dict):
        context = result.get("context")
        raw_slot = (
            context.get("slot")
            if isinstance(context, dict)
            else result.get("slot")
        )
        if raw_slot is not None:
            try:
                slot = int(raw_slot)
            except (TypeError, ValueError):
                slot = None

        raw_block_time = result.get("blockTime")
        if isinstance(raw_block_time, (int, float)):
            block_time = raw_block_time

    return RawCaptureContext(
        provider="solana_rpc",
        event_type="RPC_RESPONSE",
        transaction_signature=transaction_signature,
        slot=slot,
        block_time=block_time,
        observed_wallet=observed_wallet,
        commitment=commitment,
        technical_metadata={
            "rpc_method": method,
            "endpoint": "configured_solana_rpc",
        },
    )


class SolanaRpcClient:
    def __init__(
        self,
        *,
        rpc_url: str | None = None,
        timeout_seconds: float = 20.0,
        transport: (
            httpx.BaseTransport
            | None
        ) = None,
    ):
        self.rpc_url = (
            rpc_url
            or settings.SOLANA_RPC_URL
        ).strip()

        self.timeout_seconds = (
            timeout_seconds
        )

        self.transport = transport

    def call(
        self,
        method: str,
        params: list | None = None,
    ) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }

        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self.rpc_url,
                    json=payload,
                )

        except httpx.TimeoutException as exception:
            raise SolanaRpcError(
                "Timeout durante la richiesta "
                "al nodo Solana.",
                code="SOLANA_RPC_TIMEOUT",
                status_code=504,
            ) from exception

        except httpx.HTTPError as exception:
            raise SolanaRpcError(
                "Errore di rete durante la "
                "richiesta al nodo Solana.",
                code="SOLANA_RPC_NETWORK_ERROR",
                status_code=502,
            ) from exception

        try:
            body = response.json()

        except ValueError as exception:
            raise SolanaRpcError(
                "Il nodo Solana ha restituito "
                "una risposta non JSON.",
                code="SOLANA_RPC_INVALID_RESPONSE",
                status_code=502,
            ) from exception

        if response.is_error:
            raise SolanaRpcError(
                "Nodo Solana HTTP "
                f"{response.status_code}.",
                code="SOLANA_RPC_HTTP_ERROR",
                status_code=502,
                payload={
                    "http_status":
                        response.status_code,
                },
            )

        if not isinstance(body, dict):
            raise SolanaRpcError(
                "Formato risposta Solana "
                "non valido.",
                code="SOLANA_RPC_INVALID_RESPONSE",
                status_code=502,
            )

        if body.get("error"):
            error = body["error"]

            raise SolanaRpcError(
                str(
                    error.get("message")
                    if isinstance(error, dict)
                    else error
                ),
                code="SOLANA_RPC_ERROR",
                status_code=502,
                payload={
                    "rpc_error": error,
                },
            )

        if "result" not in body:
            raise SolanaRpcError(
                "Risposta Solana priva "
                "di result.",
                code="SOLANA_RPC_INVALID_RESPONSE",
                status_code=502,
            )

        capture_raw_blockchain_payload_safely(
            body,
            context=_rpc_capture_context(
                method,
                params or [],
                body,
            ),
        )

        return body["result"]

    def get_balance_lamports(
        self,
        address: str,
    ) -> int:
        result = self.call(
            "getBalance",
            [
                address,
                {
                    "commitment":
                        "confirmed",
                },
            ],
        )

        try:
            return int(
                result["value"]
            )

        except (
            KeyError,
            TypeError,
            ValueError,
        ) as exception:
            raise SolanaRpcError(
                "Saldo Solana non "
                "interpretabile.",
                code="SOLANA_RPC_INVALID_BALANCE",
                status_code=502,
            ) from exception

    def get_balance_sol(
        self,
        address: str,
    ) -> float:
        return (
            self.get_balance_lamports(
                address
            )
            / LAMPORTS_PER_SOL
        )

    def get_signature_status(
        self,
        signature: str,
    ) -> dict:
        result = self.call(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": True}],
        )
        values = result.get("value") if isinstance(result, dict) else None
        value = values[0] if isinstance(values, list) and values else None
        if value is None:
            return {
                "found": False,
                "confirmation_status": None,
                "confirmations": None,
                "error": None,
                "slot": None,
            }
        if not isinstance(value, dict):
            raise SolanaRpcError(
                "Stato firma Solana non valido.",
                code="SOLANA_SIGNATURE_STATUS_INVALID",
                status_code=502,
            )
        return {
            "found": True,
            "confirmation_status": value.get("confirmationStatus"),
            "confirmations": value.get("confirmations"),
            "error": value.get("err"),
            "slot": value.get("slot"),
        }

    def get_transaction_details(
        self,
        signature: str,
    ) -> dict | None:
        result = self.call(
            "getTransaction",
            [
                signature,
                {
                    "commitment": "finalized",
                    "encoding": "json",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )

        if result is None:
            return None

        if not isinstance(result, dict):
            raise SolanaRpcError(
                "Transazione Solana non interpretabile.",
                code="SOLANA_TRANSACTION_INVALID_RESPONSE",
                status_code=502,
            )

        return result


    def simulate_unsigned_transaction_base64(
        self,
        transaction_base64: str,
    ) -> dict:
        result = self.call(
            "simulateTransaction",
            [
                transaction_base64,
                {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "sigVerify": False,
                    "replaceRecentBlockhash": True,
                },
            ],
        )

        value = (
            result.get("value")
            if isinstance(result, dict)
            else None
        )

        if not isinstance(value, dict):
            raise SolanaRpcError(
                "Risposta di simulazione unsigned Solana non valida.",
                code="SOLANA_UNSIGNED_SIMULATION_INVALID_RESPONSE",
                status_code=502,
            )

        return {
            "success": value.get("err") is None,
            "error": value.get("err"),
            "units_consumed": value.get("unitsConsumed"),
            "logs": (value.get("logs") or [])[-100:],
        }


    def simulate_transaction_base64(
        self,
        transaction_base64: str,
    ) -> dict:
        result = self.call(
            "simulateTransaction",
            [
                transaction_base64,
                {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "sigVerify": True,
                    "replaceRecentBlockhash": False,
                },
            ],
        )

        value = (
            result.get("value")
            if isinstance(result, dict)
            else None
        )

        if not isinstance(value, dict):
            raise SolanaRpcError(
                "Risposta di simulazione Solana non valida.",
                code="SOLANA_SIMULATION_INVALID_RESPONSE",
                status_code=502,
            )

        if value.get("err") is not None:
            raise SolanaRpcError(
                "La simulazione della transazione LIVE è fallita.",
                code="SOLANA_SIMULATION_FAILED",
                status_code=409,
                payload={
                    "simulation_error": value.get("err"),
                    "logs": (value.get("logs") or [])[-20:],
                },
            )

        return {
            "units_consumed": value.get("unitsConsumed"),
            "logs": (value.get("logs") or [])[-20:],
        }


    def send_signed_transaction_base64(
        self,
        transaction_base64: str,
    ) -> str:
        result = self.call(
            "sendTransaction",
            [
                transaction_base64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 0,
                },
            ],
        )

        if not isinstance(result, str) or not result.strip():
            raise SolanaRpcError(
                "Firma restituita da sendTransaction non valida.",
                code="SOLANA_SEND_TRANSACTION_INVALID_RESPONSE",
                status_code=502,
            )

        return result.strip()


def solana_rpc_call(
    method: str,
    params: list | None = None,
):
    client = SolanaRpcClient()

    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": client.call(
            method,
            params,
        ),
    }


def get_solana_health():
    return solana_rpc_call(
        "getHealth"
    )


def get_wallet_balance(
    address: str,
):
    lamports = (
        SolanaRpcClient()
        .get_balance_lamports(
            address
        )
    )

    return {
        "address": address,
        "lamports": lamports,
        "sol": (
            lamports
            / LAMPORTS_PER_SOL
        ),
    }


def get_wallet_transactions(
    address: str,
    limit: int = 10,
):
    return SolanaRpcClient().call(
        "getSignaturesForAddress",
        [
            address,
            {
                "limit": limit,
            },
        ],
    )


def get_transaction_detail(
    signature: str,
):
    return SolanaRpcClient().call(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion":
                    0,
            },
        ],
    )


def analyze_wallet(
    address: str,
):
    transactions = (
        get_wallet_transactions(
            address,
            limit=10,
        )
    )

    analyzed = [
        {
            "signature":
                tx["signature"],
            "slot":
                tx["slot"],
            "status":
                tx.get(
                    "confirmationStatus"
                ),
            "success":
                tx.get("err") is None,
            "block_time":
                tx.get("blockTime"),
        }
        for tx in transactions
    ]

    return {
        "wallet": address,
        "transactions_found":
            len(analyzed),
        "transactions": analyzed,
    }


def classify_transaction(
    signature: str,
):
    tx_detail = (
        get_transaction_detail(
            signature
        )
    )

    if tx_detail is None:
        return {
            "signature": signature,
            "type": "unknown",
            "programs": [],
            "success": False,
        }

    instructions = (
        tx_detail["transaction"]
        ["message"]
        ["instructions"]
    )

    programs = [
        instruction.get(
            "program",
            "unknown",
        )
        for instruction
        in instructions
    ]

    if "vote" in programs:
        tx_type = "vote"

    elif "system" in programs:
        tx_type = "system_transfer"

    elif "spl-token" in programs:
        tx_type = "token_operation"

    else:
        tx_type = "unknown"

    return {
        "signature": signature,
        "type": tx_type,
        "programs": programs,
        "success": (
            tx_detail["meta"]["err"]
            is None
        ),
        "slot": tx_detail["slot"],
        "block_time":
            tx_detail["blockTime"],
    }
