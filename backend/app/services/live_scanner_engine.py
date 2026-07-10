import asyncio

from sqlalchemy.orm import Session

from backend.app.services.alert_engine import get_alerts


_running = False


async def live_scanner(
    db: Session,
    interval: int = 15,
):
    global _running

    _running = True

    print("===== SMARTMONEY LIVE SCANNER STARTED =====")

    while _running:

        try:
            alerts = get_alerts(
                db=db,
                min_signal_score=60,
            )

            if alerts["count"] > 0:
                print(
                    f"[LIVE] {alerts['count']} active alerts"
                )

                for alert in alerts["alerts"]:

                    print(
                        f"{alert['token']} | "
                        f"{alert['signal_score']} | "
                        f"{alert['buyers']} buyers"
                    )

        except Exception as e:
            print(e)

        await asyncio.sleep(interval)


def stop_live_scanner():
    global _running
    _running = False 