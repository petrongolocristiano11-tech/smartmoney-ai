from typing import Any

from sqlalchemy.orm import Session

from backend.app.models.paper_autopilot import (
    PaperAutopilotPolicy,
)
from backend.app.services.paper_autopilot_engine import (
    PaperAutopilotError,
    get_or_create_autopilot_policy,
)
from backend.app.services.paper_trading_engine import (
    get_paper_account,
)


MUTABLE_POLICY_FIELDS = {
    "status",
    "min_signal_score",
    "min_evidence_score",
    "min_buyers",
    "minimum_confidence",
    "max_signal_age_hours",
    "min_smart_volume_share_percent",
    "max_volume_concentration_percent",
    "blocked_risk_flags",
    "excluded_token_mints",
    "max_signals_per_run",
    "max_entries_per_run",
    "max_entries_per_day",
    "token_cooldown_hours",
    "max_position_percent_of_equity",
    "max_total_exposure_percent",
    "minimum_cash_reserve_percent",
    "minimum_order_size_sol",
    "stop_loss_percent",
    "take_profit_percent",
    "trailing_stop_enabled",
    "trailing_stop_percent",
    "max_holding_hours",
    "slippage_percent",
    "fee_percent",
    "max_consecutive_errors",
}


def _validate_final_policy(
    policy: PaperAutopilotPolicy,
    account_max_position_size_sol: float,
) -> None:
    if (
        int(
            policy.max_entries_per_run
        )
        > int(
            policy.max_entries_per_day
        )
    ):
        raise PaperAutopilotError(
            "max_entries_per_run non può "
            "superare max_entries_per_day.",
            code="INVALID_ENTRY_LIMITS",
        )

    if (
        float(
            policy
            .max_position_percent_of_equity
        )
        > float(
            policy
            .max_total_exposure_percent
        )
    ):
        raise PaperAutopilotError(
            "La percentuale massima per "
            "posizione non può superare "
            "l'esposizione totale.",
            code=(
                "INVALID_EXPOSURE_LIMITS"
            ),
        )

    if (
        float(
            policy
            .max_total_exposure_percent
        )
        + float(
            policy
            .minimum_cash_reserve_percent
        )
        > 100
    ):
        raise PaperAutopilotError(
            "Esposizione totale e riserva "
            "minima non possono superare "
            "insieme il 100%.",
            code=(
                "INVALID_CAPITAL_ALLOCATION"
            ),
        )

    if (
        float(
            policy.minimum_order_size_sol
        )
        > float(
            account_max_position_size_sol
        )
    ):
        raise PaperAutopilotError(
            "L'ordine minimo non può "
            "superare il limite massimo "
            "per posizione del conto.",
            code=(
                "MINIMUM_ORDER_ABOVE_"
                "ACCOUNT_LIMIT"
            ),
        )


def update_autopilot_policy(
    db: Session,
    account_id: int,
    updates: dict[str, Any],
) -> PaperAutopilotPolicy:
    account = get_paper_account(
        db,
        account_id,
        lock=True,
    )

    policy = (
        get_or_create_autopilot_policy(
            db,
            account_id,
        )
    )

    unknown_fields = (
        set(updates)
        - MUTABLE_POLICY_FIELDS
    )

    if unknown_fields:
        raise PaperAutopilotError(
            "Campi politica non "
            "supportati: "
            + ", ".join(
                sorted(unknown_fields)
            ),
            code=(
                "UNSUPPORTED_POLICY_FIELDS"
            ),
        )

    previous_status = str(
        policy.status
    ).upper()

    for field_name, value in (
        updates.items()
    ):
        setattr(
            policy,
            field_name,
            value,
        )

    policy.status = str(
        policy.status
    ).strip().upper()

    policy.minimum_confidence = str(
        policy.minimum_confidence
    ).strip().upper()

    policy.blocked_risk_flags = list(
        dict.fromkeys(
            str(item).strip().upper()
            for item in (
                policy.blocked_risk_flags
                or []
            )
            if str(item).strip()
        )
    )

    policy.excluded_token_mints = list(
        dict.fromkeys(
            str(item).strip()
            for item in (
                policy.excluded_token_mints
                or []
            )
            if str(item).strip()
        )
    )

    _validate_final_policy(
        policy,
        float(
            account
            .max_position_size_sol
        ),
    )

    if policy.status == "ENABLED":
        if account.status != "ACTIVE":
            raise PaperAutopilotError(
                "Il conto deve essere "
                "ACTIVE prima di abilitare "
                "Autopilot.",
                code=(
                    "ACCOUNT_NOT_ACTIVE_"
                    "FOR_AUTOPILOT"
                ),
            )

        policy.consecutive_errors = 0
        policy.paused_reason = None

    elif policy.status == "PAUSED":
        if (
            previous_status != "PAUSED"
            or not policy.paused_reason
        ):
            policy.paused_reason = (
                "Pausa manuale: le uscite "
                "automatiche restano attive, "
                "le nuove entrate sono "
                "bloccate."
            )

    elif policy.status == "DISABLED":
        policy.paused_reason = None

    try:
        db.commit()

    except Exception:
        db.rollback()
        raise

    db.refresh(policy)

    return policy 