from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.core.discovery_security import require_automation_key
from backend.app.database.session import get_db
from backend.app.services.raw_blockchain_capture_service import (
    get_raw_capture_status,
)


router = APIRouter(
    prefix="/integrity",
    tags=["Blockchain Integrity"],
    dependencies=[Depends(require_automation_key)],
)


@router.get("/raw-capture/status")
def read_raw_capture_status(
    db: Session = Depends(get_db),
):
    return get_raw_capture_status(db)
