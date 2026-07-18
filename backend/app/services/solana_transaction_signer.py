import base64
import json

from solders.keypair import Keypair
from solders.message import (
    to_bytes_versioned,
)
from solders.transaction import (
    VersionedTransaction,
)

from backend.app.core.config import settings
from backend.app.services.live_trading_errors import (
    SolanaSignerError,
)


class SolanaTransactionSigner:
    def __init__(
        self,
        *,
        private_key: str | None = None,
        expected_wallet_address: (
            str | None
        ) = None,
    ):
        self.private_key = (
            private_key
            if private_key is not None
            else (
                settings
                .LIVE_TRADING_PRIVATE_KEY
            )
        ).strip()

        self.expected_wallet_address = (
            expected_wallet_address
            if expected_wallet_address
            is not None
            else (
                settings
                .LIVE_TRADING_WALLET_ADDRESS
            )
        ).strip()

        self._keypair: Keypair | None = None

    def _load_keypair(self) -> Keypair:
        if self._keypair is not None:
            return self._keypair

        if not self.private_key:
            raise SolanaSignerError(
                "Chiave privata Live Trading "
                "non configurata.",
                code="LIVE_PRIVATE_KEY_MISSING",
                status_code=503,
            )

        try:
            if self.private_key.startswith("["):
                raw = json.loads(
                    self.private_key
                )

                if not isinstance(raw, list):
                    raise ValueError(
                        "Formato JSON non valido"
                    )

                keypair = Keypair.from_bytes(
                    bytes(
                        int(value)
                        for value in raw
                    )
                )

            else:
                keypair = (
                    Keypair
                    .from_base58_string(
                        self.private_key
                    )
                )

        except Exception as exception:
            raise SolanaSignerError(
                "Chiave privata Solana "
                "non valida.",
                code="LIVE_PRIVATE_KEY_INVALID",
                status_code=503,
            ) from exception

        public_key = str(
            keypair.pubkey()
        )

        if (
            self.expected_wallet_address
            and public_key
            != self.expected_wallet_address
        ):
            raise SolanaSignerError(
                "La chiave privata non "
                "corrisponde al wallet "
                "configurato.",
                code="LIVE_WALLET_KEY_MISMATCH",
                status_code=503,
                payload={
                    "derived_wallet":
                        public_key,
                },
            )

        self._keypair = keypair

        return keypair

    @property
    def wallet_address(self) -> str:
        return str(
            self._load_keypair().pubkey()
        )

    def sign_base64_versioned_transaction(
        self,
        transaction_base64: str,
    ) -> str:
        keypair = self._load_keypair()

        try:
            transaction = (
                VersionedTransaction
                .from_bytes(
                    base64.b64decode(
                        transaction_base64,
                        validate=True,
                    )
                )
            )

        except Exception as exception:
            raise SolanaSignerError(
                "Transazione Jupiter non "
                "valida o non decodificabile.",
                code="INVALID_JUPITER_TRANSACTION",
                status_code=502,
            ) from exception

        message = transaction.message

        required_signatures = int(
            message
            .header
            .num_required_signatures
        )

        signer_keys = list(
            message.account_keys
        )[:required_signatures]

        try:
            signer_index = signer_keys.index(
                keypair.pubkey()
            )

        except ValueError as exception:
            raise SolanaSignerError(
                "Il wallet configurato non "
                "è tra i firmatari richiesti.",
                code="WALLET_NOT_REQUIRED_SIGNER",
                status_code=502,
            ) from exception

        signatures = list(
            transaction.signatures
        )

        if (
            len(signatures)
            != required_signatures
        ):
            raise SolanaSignerError(
                "Numero di firme della "
                "transazione non valido.",
                code=(
                    "INVALID_TRANSACTION_SIGNATURES"
                ),
                status_code=502,
            )

        signatures[
            signer_index
        ] = keypair.sign_message(
            to_bytes_versioned(
                message
            )
        )

        signed_transaction = (
            VersionedTransaction.populate(
                message,
                signatures,
            )
        )

        return base64.b64encode(
            bytes(signed_transaction)
        ).decode("ascii") 