from sqlalchemy.orm import Session

from backend.app.models.discovered_wallet import DiscoveredWallet


def save_discovered_wallet(
    db: Session,
    wallet_address: str,
    discovered_from_token: str,
    smart_score: float,
    roi_percent: float,
    win_rate_percent: float,
    profit_loss_sol: float,
    reliable_positions: int,
):
    existing = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == wallet_address)
        .first()
    )

    if existing:
        existing.smart_score = smart_score
        existing.roi_percent = roi_percent
        existing.win_rate_percent = win_rate_percent
        existing.profit_loss_sol = profit_loss_sol
        existing.reliable_positions = reliable_positions
        existing.discovered_from_token = discovered_from_token
        existing.status = "UPDATED"

        db.commit()
        db.refresh(existing)

        return existing

    wallet = DiscoveredWallet(
        wallet_address=wallet_address,
        discovered_from_token=discovered_from_token,
        smart_score=smart_score,
        roi_percent=roi_percent,
        win_rate_percent=win_rate_percent,
        profit_loss_sol=profit_loss_sol,
        reliable_positions=reliable_positions,
        status="DISCOVERED",
    )

    db.add(wallet)
    db.commit()
    db.refresh(wallet)

    return wallet 