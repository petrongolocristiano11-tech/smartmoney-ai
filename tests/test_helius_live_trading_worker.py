from backend.app.workers.helius_live_trading_worker import (
    build_logs_subscription_request,
    build_policy_fingerprint,
    parse_logs_notification,
)


WALLET = "W" * 32


def test_logs_subscription_contains_one_wallet():
    request = (
        build_logs_subscription_request(
            1000,
            WALLET,
        )
    )

    assert (
        request["method"]
        == "logsSubscribe"
    )

    assert (
        request["params"][0]
        == {
            "mentions": [
                WALLET
            ]
        }
    )


def test_logs_notification_is_mapped_to_wallet():
    result = parse_logs_notification(
        {
            "method":
                "logsNotification",
            "params": {
                "subscription":
                    123,
                "result": {
                    "value": {
                        "signature":
                            "signature-1",
                        "err":
                            None,
                    }
                },
            },
        },
        {
            123: WALLET,
        },
    )

    assert result == (
        "signature-1",
        WALLET,
    )


def test_policy_fingerprint_changes_with_wallets():
    first = build_policy_fingerprint(
        mode="DRY_RUN",
        stream_enabled=True,
        kill_switch=False,
        wallets=(
            "A" * 32,
        ),
        updated_at="2026-01-01",
    )

    second = build_policy_fingerprint(
        mode="DRY_RUN",
        stream_enabled=True,
        kill_switch=False,
        wallets=(
            "B" * 32,
        ),
        updated_at="2026-01-01",
    )

    assert first != second 