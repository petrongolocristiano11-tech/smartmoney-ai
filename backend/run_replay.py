import argparse

from backend.app.database.session import SessionLocal
from backend.app.models.trade import Trade
from backend.app.services.helius_stream import process_signature


def get_latest_trade():
    db = SessionLocal()

    try:
        trade = (
            db.query(Trade)
            .filter(Trade.signature.isnot(None))
            .filter(Trade.wallet_address.isnot(None))
            .order_by(Trade.created_at.desc())
            .first()
        )

        if trade is None:
            return None

        return {
            "signature": trade.signature,
            "wallet": trade.wallet_address,
        }

    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Replay di una transazione nella pipeline live."
    )

    parser.add_argument(
        "--signature",
        type=str,
        default=None,
    )

    parser.add_argument(
        "--wallet",
        type=str,
        default=None,
    )

    args = parser.parse_args()

    signature = args.signature
    wallet = args.wallet

    if not signature or not wallet:
        latest_trade = get_latest_trade()

        if latest_trade is None:
            print("Nessun trade disponibile nel database.")
            return

        signature = latest_trade["signature"]
        wallet = latest_trade["wallet"]

    print("=" * 60)
    print("SMARTMONEY LIVE PIPELINE REPLAY")
    print(f"Wallet: {wallet}")
    print(f"Signature: {signature}")
    print("=" * 60)

    process_signature(
        signature=signature,
        monitored_wallets={wallet},
    )

    print()
    print("Replay completato.")


if __name__ == "__main__":
    main() 