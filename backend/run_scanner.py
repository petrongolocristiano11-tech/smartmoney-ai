import asyncio

from backend.app.services.helius_stream import run_helius_stream


def main():
    try:
        asyncio.run(
            run_helius_stream(
                min_smart_score=60,
                reconnect_delay=5,
            )
        )

    except KeyboardInterrupt:
        print()
        print("Helius Live Scanner arrestato.")


if __name__ == "__main__":
    main() 