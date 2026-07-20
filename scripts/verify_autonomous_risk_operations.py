"""Static acceptance checks for the autonomous risk/operations milestone."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from backend.app.main import app
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.models.live_position_monitor import LivePositionMonitorState
from backend.app.models.live_risk_state import LiveRiskState
from backend.app.models.live_trading_policy import LiveTradingPolicy


REQUIRED_PATHS = {
    "/live-trading/operations/overview",
    "/live-trading/operations/run-once",
    "/live-trading/operations/reconcile",
    "/live-trading/operations/risk/cooldown/reset",
}


def main() -> None:
    openapi = app.openapi()
    paths = set(openapi.get("paths", {}))
    missing = sorted(REQUIRED_PATHS - paths)
    if missing:
        raise SystemExit(f"Endpoint operativi mancanti: {', '.join(missing)}")

    expected_columns = {
        LiveTradingPolicy: {
            "automatic_exits_enabled",
            "take_profit_percent",
            "stop_loss_percent",
            "trailing_stop_percent",
            "max_open_positions",
            "max_token_exposure_sol",
            "max_portfolio_drawdown_percent",
        },
        LivePosition: {
            "current_value_sol",
            "unrealized_pnl_sol",
            "high_watermark_value_sol",
            "trailing_stop_value_sol",
            "exit_pending",
        },
        LiveCopyOrder: {
            "execution_origin",
            "exit_reason",
            "reconciliation_status",
            "confirmation_status",
        },
    }
    for model, required in expected_columns.items():
        actual = set(model.__table__.columns.keys())
        missing_columns = sorted(required - actual)
        if missing_columns:
            raise SystemExit(
                f"Colonne mancanti in {model.__tablename__}: "
                f"{', '.join(missing_columns)}"
            )

    assert LiveRiskState.__tablename__ == "live_risk_states"
    assert "loss_streak_reset_at" in LiveRiskState.__table__.columns
    assert LivePositionMonitorState.__tablename__ == "live_position_monitor_states"

    print(f"OpenAPI: {len(paths)} percorsi totali")
    print("Endpoint operativi: 4/4")
    print("Modelli rischio, monitor, posizioni e riconciliazione: OK")


if __name__ == "__main__":
    main()
