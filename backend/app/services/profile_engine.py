from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.smart_score_engine import calculate_smart_score


def ensure_wallet_profiles_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS wallet_profiles (
                id SERIAL PRIMARY KEY,
                wallet_address VARCHAR(64) UNIQUE,
                smart_score FLOAT DEFAULT 0,
                roi FLOAT DEFAULT 0,
                win_rate FLOAT DEFAULT 0,
                profit FLOAT DEFAULT 0,
                activity INTEGER DEFAULT 0,
                influence_score FLOAT DEFAULT 0,
                conviction_score FLOAT DEFAULT 0,
                early_buyer_score FLOAT DEFAULT 0,
                prediction_score FLOAT DEFAULT 0,
                holding_score FLOAT DEFAULT 0,
                classification VARCHAR(50) DEFAULT 'NORMAL',
                traits TEXT DEFAULT 'NORMAL',
                dna VARCHAR(50) DEFAULT 'NORMAL',
                risk VARCHAR(20) DEFAULT 'MEDIUM',
                version VARCHAR(20) DEFAULT '3.0',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    columns = {
        "holding_score": "FLOAT DEFAULT 0",
        "classification": "VARCHAR(50) DEFAULT 'NORMAL'",
        "traits": "TEXT DEFAULT 'NORMAL'",
        "created_at": "TIMESTAMPTZ DEFAULT NOW()",
        "updated_at": "TIMESTAMPTZ DEFAULT NOW()",
    }

    for column, definition in columns.items():
        db.execute(
            text(
                f"""
                ALTER TABLE wallet_profiles
                ADD COLUMN IF NOT EXISTS {column} {definition}
                """
            )
        )

    db.commit()


def build_wallet_profile(db: Session, wallet_address: str):
    ensure_wallet_profiles_table(db)

    score = calculate_smart_score(db, wallet_address)
    dna = score["dna"]
    analytics = dna["analytics"]
    early = dna["early_buyer"]
    influence = dna["influence"]
    conviction = dna["conviction"]
    holding = dna["holding"]
    prediction = dna["prediction"]

    profile = (
        db.query(WalletProfile)
        .filter(WalletProfile.wallet_address == wallet_address)
        .first()
    )

    if profile is None:
        profile = WalletProfile(wallet_address=wallet_address)
        db.add(profile)

    profile.smart_score = score["smart_score"]
    profile.version = score["version"]

    profile.roi = analytics["total_roi_percent"]
    profile.win_rate = analytics["win_rate_percent"]
    profile.profit = analytics["total_profit_loss_sol"]
    profile.activity = analytics["reliable_positions"]

    profile.influence_score = influence["influence_score"]
    profile.conviction_score = conviction["conviction_score"]
    profile.early_buyer_score = early["early_buyer_score"]
    profile.prediction_score = prediction["prediction_score"]
    profile.holding_score = holding["holding_score"]

    profile.classification = dna["classification"]
    profile.traits = ",".join(dna["traits"])

    profile.dna = dna["classification"]
    profile.risk = analytics["risk_level"]

    db.commit()
    db.refresh(profile)

    return {
        "wallet": profile.wallet_address,
        "smart_score": profile.smart_score,
        "version": profile.version,
        "classification": profile.classification,
        "traits": profile.traits.split(",") if profile.traits else [],
        "roi_percent": profile.roi,
        "win_rate_percent": profile.win_rate,
        "profit_loss_sol": profile.profit,
        "activity": profile.activity,
        "influence_score": profile.influence_score,
        "conviction_score": profile.conviction_score,
        "early_buyer_score": profile.early_buyer_score,
        "prediction_score": profile.prediction_score,
        "holding_score": profile.holding_score,
        "risk": profile.risk,
    } 