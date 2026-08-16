from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.learning_session import LearningSession
from app.models.telemetry_event import TelemetryEvent
from app.schemas.session import TelemetryBatchIn

router = APIRouter(tags=["telemetry"])


@router.post("/sessions/{session_id}/events", status_code=204)
def ingest_events(session_id: str, batch: TelemetryBatchIn, db: Session = Depends(get_db)) -> None:
    session = db.get(LearningSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

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
