from sqlalchemy.orm import Session

from app.models.learning_session import LearningSession
from app.rl.policy import record_outcome


def on_session_end(db: Session, session: LearningSession) -> tuple[float, dict]:
    """Entry point called by app/sessions/router.py on session completion. Delegates to the RL
    policy orchestrator: scores the session, computes the resulting next MDP state and reward,
    performs the Q-learning update, and records the full (state, action, reward, next_state,
    done) transition. See app/rl/policy.py::record_outcome for the actual logic."""
    return record_outcome(db, session)
