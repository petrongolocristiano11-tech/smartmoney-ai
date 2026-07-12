import asyncio
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.database.session import SessionLocal, get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.alert_engine import get_alerts


router = APIRouter(
    prefix="/live",
    tags=["Live Scanner"],
)


def iso_datetime(value):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def trade_to_payload(trade: Trade):
    return {
        "id": trade.id,
        "type": "TRADE",
        "timestamp": iso_datetime(
            trade.block_time or trade.created_at
        ),
        "wallet": trade.wallet_address,
        "side": trade.side,
        "token": trade.token_mint,
        "token_amount": trade.token_amount,
        "sol_amount": trade.sol_amount,
        "source": trade.source,
        "signature": trade.signature,
        "success": trade.success,
    }


def wallet_to_payload(wallet: DiscoveredWallet):
    return {
        "id": wallet.id,
        "type": "WALLET_DISCOVERED",
        "timestamp": iso_datetime(wallet.created_at),
        "wallet": wallet.wallet_address,
        "token": wallet.discovered_from_token,
        "smart_score": wallet.smart_score,
        "roi_percent": wallet.roi_percent,
        "win_rate_percent": wallet.win_rate_percent,
        "profit_loss_sol": wallet.profit_loss_sol,
        "status": wallet.status,
    }


def alert_key(alert: dict):
    return (
        f"{alert.get('type')}::"
        f"{alert.get('token')}::"
        f"{alert.get('signal_score')}::"
        f"{alert.get('buyers')}"
    )


def alert_to_payload(alert: dict):
    return {
        **alert,
        "id": alert_key(alert),
        "timestamp": utc_now(),
    }


def build_status(db: Session):
    latest_trade = (
        db.query(Trade)
        .order_by(Trade.id.desc())
        .first()
    )

    latest_wallet = (
        db.query(DiscoveredWallet)
        .order_by(DiscoveredWallet.id.desc())
        .first()
    )

    return {
        "status": "online",
        "smart_wallets_monitored": (
            db.query(WalletProfile)
            .filter(WalletProfile.smart_score >= 60)
            .count()
        ),
        "total_trades": db.query(Trade).count(),
        "discovered_wallets": (
            db.query(DiscoveredWallet).count()
        ),
        "latest_trade_at": (
            iso_datetime(
                latest_trade.block_time
                or latest_trade.created_at
            )
            if latest_trade
            else None
        ),
        "latest_wallet_at": (
            iso_datetime(latest_wallet.created_at)
            if latest_wallet
            else None
        ),
        "server_time": utc_now(),
    }


def build_snapshot(min_alert_score: float):
    db = SessionLocal()

    try:
        recent_trades = (
            db.query(Trade)
            .order_by(Trade.id.desc())
            .limit(25)
            .all()
        )

        recent_wallets = (
            db.query(DiscoveredWallet)
            .order_by(DiscoveredWallet.id.desc())
            .limit(15)
            .all()
        )

        alerts = get_alerts(
            db=db,
            min_signal_score=min_alert_score,
        )["alerts"][:10]

        trades_payload = [
            trade_to_payload(trade)
            for trade in reversed(recent_trades)
        ]

        wallets_payload = [
            wallet_to_payload(wallet)
            for wallet in reversed(recent_wallets)
        ]

        alerts_payload = [
            alert_to_payload(alert)
            for alert in alerts
        ]

        return {
            "timestamp": utc_now(),
            "status": build_status(db),
            "recent_trades": trades_payload,
            "recent_wallets": wallets_payload,
            "alerts": alerts_payload,
            "cursor": {
                "trade_id": max(
                    [trade.id for trade in recent_trades],
                    default=0,
                ),
                "wallet_id": max(
                    [wallet.id for wallet in recent_wallets],
                    default=0,
                ),
            },
        }

    finally:
        db.close()


def fetch_new_database_events(
    last_trade_id: int,
    last_wallet_id: int,
):
    db = SessionLocal()

    try:
        trades = (
            db.query(Trade)
            .filter(Trade.id > last_trade_id)
            .order_by(Trade.id.asc())
            .limit(100)
            .all()
        )

        wallets = (
            db.query(DiscoveredWallet)
            .filter(DiscoveredWallet.id > last_wallet_id)
            .order_by(DiscoveredWallet.id.asc())
            .limit(100)
            .all()
        )

        return {
            "trades": [
                trade_to_payload(trade)
                for trade in trades
            ],
            "wallets": [
                wallet_to_payload(wallet)
                for wallet in wallets
            ],
            "last_trade_id": (
                trades[-1].id
                if trades
                else last_trade_id
            ),
            "last_wallet_id": (
                wallets[-1].id
                if wallets
                else last_wallet_id
            ),
        }

    finally:
        db.close()


def fetch_current_alerts(min_alert_score: float):
    db = SessionLocal()

    try:
        alerts = get_alerts(
            db=db,
            min_signal_score=min_alert_score,
        )["alerts"]

        return [
            alert_to_payload(alert)
            for alert in alerts
        ]

    finally:
        db.close()


def format_sse(
    event_name: str,
    data: dict,
    event_id: str | None = None,
):
    lines = []

    if event_id:
        lines.append(f"id: {event_id}")

    lines.append(f"event: {event_name}")

    serialized_data = json.dumps(
        data,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )

    for line in serialized_data.splitlines():
        lines.append(f"data: {line}")

    return "\n".join(lines) + "\n\n"


@router.get("/status")
def live_status(
    db: Session = Depends(get_db),
):
    return build_status(db)


@router.get("/stream")
async def live_stream(
    request: Request,
    interval_seconds: float = Query(
        default=2,
        ge=1,
        le=10,
    ),
    min_alert_score: float = Query(
        default=50,
        ge=0,
        le=100,
    ),
):
    async def event_generator():
        snapshot = await asyncio.to_thread(
            build_snapshot,
            min_alert_score,
        )

        last_trade_id = snapshot["cursor"]["trade_id"]
        last_wallet_id = snapshot["cursor"]["wallet_id"]

        seen_alerts = {
            alert["id"]
            for alert in snapshot["alerts"]
        }

        yield format_sse(
            event_name="snapshot",
            data=snapshot,
            event_id=f"snapshot-{int(time.time())}",
        )

        last_heartbeat = time.monotonic()
        alert_check_counter = 0

        while True:
            if await request.is_disconnected():
                break

            database_events = await asyncio.to_thread(
                fetch_new_database_events,
                last_trade_id,
                last_wallet_id,
            )

            last_trade_id = database_events[
                "last_trade_id"
            ]

            last_wallet_id = database_events[
                "last_wallet_id"
            ]

            for trade in database_events["trades"]:
                yield format_sse(
                    event_name="trade",
                    data=trade,
                    event_id=f"trade-{trade['id']}",
                )

            for wallet in database_events["wallets"]:
                yield format_sse(
                    event_name="wallet",
                    data=wallet,
                    event_id=f"wallet-{wallet['id']}",
                )

            alert_check_counter += 1

            if alert_check_counter >= 5:
                alert_check_counter = 0

                current_alerts = await asyncio.to_thread(
                    fetch_current_alerts,
                    min_alert_score,
                )

                for alert in current_alerts:
                    if alert["id"] in seen_alerts:
                        continue

                    seen_alerts.add(alert["id"])

                    yield format_sse(
                        event_name="alert",
                        data=alert,
                        event_id=f"alert-{alert['id']}",
                    )

                if len(seen_alerts) > 500:
                    seen_alerts = {
                        alert["id"]
                        for alert in current_alerts
                    }

            if time.monotonic() - last_heartbeat >= 15:
                last_heartbeat = time.monotonic()

                yield format_sse(
                    event_name="heartbeat",
                    data={
                        "timestamp": utc_now(),
                        "status": "online",
                    },
                )

            await asyncio.sleep(interval_seconds)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    ) 