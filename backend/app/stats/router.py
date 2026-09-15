from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.user import User
from app.schemas.stats import StatsOut
from app.stats.aggregation import compute_stats

router = APIRouter(tags=["stats"])


@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StatsOut:
    return compute_stats(db, user)
