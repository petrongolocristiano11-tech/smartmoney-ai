import pytest
from fastapi import HTTPException

from backend.app.core import (
    discovery_security,
)
from backend.app.core.config import (
    settings,
)


VALID_KEY = "a" * 32


def test_valid_automation_key(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "AUTOMATION_API_KEY",
        VALID_KEY,
    )

    discovery_security.require_automation_key(
        VALID_KEY
    )


def test_missing_automation_key_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "AUTOMATION_API_KEY",
        VALID_KEY,
    )

    with pytest.raises(
        HTTPException
    ) as exception:
        discovery_security.require_automation_key(
            None
        )

    assert (
        exception.value.status_code
        == 401
    )


def test_wrong_automation_key_is_rejected(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "AUTOMATION_API_KEY",
        VALID_KEY,
    )

    with pytest.raises(
        HTTPException
    ) as exception:
        discovery_security.require_automation_key(
            "wrong-key"
        )

    assert (
        exception.value.status_code
        == 401
    )


def test_unconfigured_automation_returns_503(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "AUTOMATION_API_KEY",
        "",
    )

    with pytest.raises(
        HTTPException
    ) as exception:
        discovery_security.require_automation_key(
            VALID_KEY
        )

    assert (
        exception.value.status_code
        == 503
    )


def test_public_discovery_has_cooldown(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "PUBLIC_DISCOVERY_COOLDOWN_SECONDS",
        120,
    )

    monkeypatch.setattr(
        discovery_security,
        "_last_public_discovery_at",
        0.0,
    )

    discovery_security.enforce_public_discovery_cooldown()

    with pytest.raises(
        HTTPException
    ) as exception:
        discovery_security.enforce_public_discovery_cooldown()

    assert (
        exception.value.status_code
        == 429
    )

    assert (
        "Retry-After"
        in exception.value.headers
    ) 