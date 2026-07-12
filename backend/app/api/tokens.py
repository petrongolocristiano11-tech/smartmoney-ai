from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.database.session import get_db
from backend.app.services.token_intelligence_engine import (
    calculate_token_intelligence,
)


router = APIRouter(
    prefix="/tokens",
    tags=["Token Intelligence"],
)


@router.get("/{token_mint}")
def get_token_intelligence(
    token_mint: str,
    db: Session = Depends(get_db),
):
    intelligence = calculate_token_intelligence(
        db=db,
        token_mint=token_mint,
    )

    if intelligence is None:
        raise HTTPException(
            status_code=404,
            detail="Nessun trade trovato per questo token.",
        )

    return intelligence 