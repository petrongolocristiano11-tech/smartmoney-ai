from datetime import datetime, timedelta, UTC

CACHE_MINUTES = 30


def needs_sync(wallet) -> bool:
    """
    True = bisogna interrogare Helius.
    False = i dati sono ancora freschi.
    """

    if wallet.last_sync is None:
        return True

    now = datetime.now(UTC)

    return (now - wallet.last_sync) > timedelta(minutes=CACHE_MINUTES) 