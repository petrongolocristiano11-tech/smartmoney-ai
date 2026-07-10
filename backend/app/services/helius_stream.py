import asyncio
import json
from collections import deque

import websockets

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.alert_engine import get_alerts
from backend.app.services.event_engine import wallet_buy_event
from backend.app.services.helius import get_enhanced_transaction
from backend.app.services.profile_engine import build_wallet_profile
from backend.app.services.trade_engine import (
    build_trade,
    build_trade_data,
    normalize_swap,
)
from backend.app.services.trade_service import create_trade_if_not_exists


SUBSCRIPTION_ID_START = 1000
MAX_RECENT_SIGNATURES = 5000


def get_helius_websocket_url() -> str:
    return (
        "wss://mainnet.helius-rpc.com/"
        f"?api-key={settings.HELIUS_API_KEY}"
    )


def get_monitored_wallets(
    min_smart_score: float = 60,
    limit: int = 100,
) -> list[str]:
    db = SessionLocal()

    try:
        rows = (
            db.query(WalletProfile.wallet_address)
            .filter(WalletProfile.smart_score >= min_smart_score)
            .order_by(WalletProfile.smart_score.desc())
            .limit(limit)
            .all()
        )

        return [row[0] for row in rows]

    finally:
        db.close()


def build_logs_subscription_request(
    request_id: int,
    wallet_address: str,
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "logsSubscribe",
        "params": [
            {
                "mentions": [wallet_address],
            },
            {
                "commitment": "confirmed",
            },
        ],
    }


def process_signature(
    signature: str,
    monitored_wallets: set[str],
) -> None:
    db = SessionLocal()

    try:
        transactions = get_enhanced_transaction(signature)

        if not transactions:
            return

        for transaction in transactions:
            if transaction.get("type") != "SWAP":
                continue

            wallet_address = transaction.get("feePayer")

            if not wallet_address:
                continue

            if wallet_address not in monitored_wallets:
                continue

            normalized_swap = normalize_swap(transaction)

            if not normalized_swap:
                continue

            trade = build_trade(normalized_swap)

            if not trade:
                continue

            trade_data = build_trade_data(
                wallet_address,
                trade,
            )

            create_trade_if_not_exists(
                db,
                trade_data,
            )

            profile = build_wallet_profile(
                db=db,
                wallet_address=wallet_address,
            )

            print()
            print("=" * 60)
            print("REAL-TIME SWAP IMPORTED")
            print(f"Wallet: {wallet_address}")
            print(f"Signature: {signature}")
            print(f"Smart Score: {profile['smart_score']}")
            print("=" * 60)

            alerts = get_alerts(
                db=db,
                min_signal_score=50,
            )

            token_mint = trade_data.get("token_mint")

            for alert in alerts["alerts"]:
                if alert["token"] != token_mint:
                    continue

                event = wallet_buy_event(
                    wallet=alert["leader_wallet"],
                    token=alert["token"],
                    amount=alert["total_volume_sol"],
                )

                print("NEW REAL-TIME ALERT")
                print(event)

    except Exception as error:
        db.rollback()
        print(f"[TRANSACTION ERROR] {signature}: {error}")

    finally:
        db.close()


async def subscribe_wallets(
    websocket,
    wallets: list[str],
) -> dict[int, str]:
    request_wallet_map: dict[int, str] = {}

    for index, wallet in enumerate(wallets):
        request_id = SUBSCRIPTION_ID_START + index

        request_wallet_map[request_id] = wallet

        request = build_logs_subscription_request(
            request_id=request_id,
            wallet_address=wallet,
        )

        await websocket.send(
            json.dumps(request)
        )

    return request_wallet_map


async def run_helius_stream(
    min_smart_score: float = 60,
    reconnect_delay: int = 5,
) -> None:
    recent_signatures: set[str] = set()
    recent_order: deque[str] = deque()

    while True:
        wallets = get_monitored_wallets(
            min_smart_score=min_smart_score,
        )

        if not wallets:
            print(
                "Nessun WalletProfile con Smart Score "
                f">= {min_smart_score}"
            )
            await asyncio.sleep(30)
            continue

        monitored_wallets = set(wallets)

        print("=" * 60)
        print("SMARTMONEY AI — HELIUS FREE LIVE STREAM")
        print(f"Wallet monitorati: {len(wallets)}")
        print(f"Smart Score minimo: {min_smart_score}")
        print("Metodo: logsSubscribe")
        print("=" * 60)

        try:
            async with websockets.connect(
                get_helius_websocket_url(),
                ping_interval=30,
                ping_timeout=20,
                close_timeout=10,
                max_size=None,
            ) as websocket:
                request_wallet_map = await subscribe_wallets(
                    websocket,
                    wallets,
                )

                active_subscriptions = 0

                async for raw_message in websocket:
                    message = json.loads(raw_message)

                    request_id = message.get("id")

                    if request_id in request_wallet_map:
                        wallet = request_wallet_map[request_id]

                        if "error" in message:
                            print(
                                f"[SUBSCRIPTION ERROR] {wallet}: "
                                f"{message['error']}"
                            )
                            continue

                        if "result" in message:
                            active_subscriptions += 1

                            print(
                                f"[SUBSCRIBED {active_subscriptions}/"
                                f"{len(wallets)}] {wallet}"
                            )
                            continue

                    if message.get("method") != "logsNotification":
                        continue

                    value = (
                        message.get("params", {})
                        .get("result", {})
                        .get("value", {})
                    )

                    if value.get("err") is not None:
                        continue

                    signature = value.get("signature")

                    if not signature:
                        continue

                    if signature in recent_signatures:
                        continue

                    recent_signatures.add(signature)
                    recent_order.append(signature)

                    if len(recent_order) > MAX_RECENT_SIGNATURES:
                        old_signature = recent_order.popleft()
                        recent_signatures.discard(old_signature)

                    print(f"[LIVE SIGNATURE] {signature}")

                    await asyncio.to_thread(
                        process_signature,
                        signature,
                        monitored_wallets,
                    )

        except asyncio.CancelledError:
            raise

        except KeyboardInterrupt:
            raise

        except Exception as error:
            print(f"[WEBSOCKET ERROR] {error}")
            print(
                f"Riconnessione tra {reconnect_delay} secondi..."
            )

            await asyncio.sleep(reconnect_delay) 