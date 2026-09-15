from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_owned_session
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User
from app.schemas.session import TelemetryBatchIn

router = APIRouter(tags=["telemetry"])


@router.post("/sessions/{session_id}/events", status_code=204)
def ingest_events(
    session_id: str,
    batch: TelemetryBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_owned_session(db, session_id, user)

    for event in batch.events:
        db.add(
            TelemetryEvent(
                session_id=session_id,
                event_type=event.event_type,
                payload=event.payload,
                client_ts=event.client_ts,
            )
        )
    db.commit()
