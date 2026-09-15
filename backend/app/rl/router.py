from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import get_current_user, require_owned_chat
from app.models.q_state import QState
from app.models.rl_transition import RLTransition
from app.rl import bandit, qlearning
from app.rl.actions import IMPLEMENTED_MODES
from app.rl.policy import POLICY_Q_LEARNING, active_policy, completed_session_count, choose_action
from app.models.user import User
from app.rl.state import parse_state_key
from app.schemas.rl import PolicyStateOut, QTableEntryOut, RLTransitionOut, SuggestModeOut

router = APIRouter(tags=["rl"])

RECENT_TRANSITIONS_LIMIT = 20


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@router.get("/chats/{chat_id}/suggest-mode", response_model=SuggestModeOut)
def suggest_mode(
    chat_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> SuggestModeOut:
    chat = require_owned_chat(db, chat_id, user)
    decision = choose_action(db, user, chat)
    confidence = _clamp01(decision.action_scores.get(decision.mode, 0.0))

    return SuggestModeOut(
        mode=decision.mode,
        confidence=confidence,
        policy=decision.policy,
        epsilon=decision.epsilon,
        state_key=decision.state.key,
        state=decision.state.as_dict(),
        action_scores=decision.action_scores,
    )


@router.get("/rl/policy-state", response_model=PolicyStateOut)
def policy_state(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> PolicyStateOut:
    """Debug/inspection endpoint: the full picture of where this user's RL policy currently
    stands — which regime is active, the legacy cold-start bandit params, every visited
    (state, action) pair in the Q-table, and the most recent recorded transitions. Exists so the
    Q-learning behavior can actually be demonstrated and debugged, not just trusted."""
    settings = get_settings()

    bandit_params = {}
    for mode in IMPLEMENTED_MODES:
        state = bandit.get_or_create_state(db, user.id, mode)
        bandit_params[mode] = state.params_json

    policy_name = active_policy(db, user.id)
    epsilon = qlearning.current_epsilon(db, user.id) if policy_name == POLICY_Q_LEARNING else None

    q_rows = db.query(QState).filter_by(user_id=user.id).order_by(QState.updated_at.desc()).all()
    q_table = [
        QTableEntryOut(
            state_key=row.state_key,
            state=parse_state_key(row.state_key),
            action=row.action,
            q_value=row.q_value,
            update_count=row.update_count,
            updated_at=row.updated_at,
        )
        for row in q_rows
    ]

    transition_rows = (
        db.query(RLTransition)
        .filter_by(user_id=user.id)
        .order_by(RLTransition.created_at.desc())
        .limit(RECENT_TRANSITIONS_LIMIT)
        .all()
    )
    recent_transitions = [
        RLTransitionOut(
            id=t.id,
            chat_id=t.chat_id,
            session_id=t.session_id,
            state_key=t.state_key,
            state=t.state_json,
            action=t.action,
            reward=t.reward,
            next_state_key=t.next_state_key,
            next_state=t.next_state_json,
            done=t.done,
            policy=t.policy,
            epsilon=t.epsilon,
            created_at=t.created_at,
        )
        for t in transition_rows
    ]

    return PolicyStateOut(
        user_id=user.id,
        active_policy=policy_name,
        epsilon=epsilon,
        completed_sessions=completed_session_count(db, user.id),
        cold_start_threshold=settings.rl_cold_start_session_threshold,
        bandit_params=bandit_params,
        q_table=q_table,
        recent_transitions=recent_transitions,
    )
