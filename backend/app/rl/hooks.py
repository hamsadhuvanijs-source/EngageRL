from sqlalchemy.orm import Session

from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.rl import bandit
from app.telemetry.scoring import compute_engagement_score


def on_session_end(db: Session, session: LearningSession) -> tuple[float, dict]:
    """Score the finished session and fold the result into the bandit for its mode."""
    score = compute_engagement_score(db, session)
    session.engagement_score = score
    db.commit()

    content = db.get(GeneratedContent, session.generated_content_id)
    updated_params = bandit.update(db, session.user_id, content.mode, score)
    return score, updated_params
