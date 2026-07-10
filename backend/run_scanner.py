import time

from backend.app.database.session import SessionLocal
from backend.app.services.alert_engine import get_alerts
from backend.app.services.event_engine import wallet_buy_event


def main():

    print("=" * 60)
    print("SMARTMONEY AI LIVE SCANNER")
    print("=" * 60)

    while True:

        db = SessionLocal()

        try:

            alerts = get_alerts(
                db=db,
                min_signal_score=50,
            )

            if alerts["count"] > 0:

                print()
                print("=" * 60)
                print(f"ACTIVE ALERTS: {alerts['count']}")
                print("=" * 60)

                for alert in alerts["alerts"]:

                    event = wallet_buy_event(
                        wallet=alert["leader_wallet"],
                        token=alert["token"],
                        amount=alert["total_volume_sol"],
                    )

                    print(event)

                    print(
                        f"[{alert['signal_score']:.2f}] "
                        f"{alert['token']} | "
                        f"buyers={alert['buyers']} | "
                        f"ROI={alert['average_roi']}%"
                    )

            else:

                print("No alerts")

        except Exception as e:

            print(f"[SCANNER ERROR] {e}")

        finally:

            db.close()

        time.sleep(15)


if __name__ == "__main__":
    main() 