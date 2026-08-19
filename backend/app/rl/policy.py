"""Hybrid policy orchestrator — the single entry point the rest of the app talks to for "what
should this learner do next" and "here's what happened, learn from it".

Two policies, cleanly separated:

  - COLD START (app/rl/bandit.py, Thompson sampling): used only while a user has fewer than
    `settings.rl_cold_start_session_threshold` completed sessions. With that little history, the
    Q-table for this user is empty or nearly so, and per-state action-values would be
    meaningless noise or arbitrary ties — Thompson sampling over a simple per-mode Beta posterior
    is a much better way to explore sensibly during this phase.
  - Q-LEARNING (app/rl/qlearning.py): the main, long-term policy once cold start ends.
    Epsilon-greedy action selection over Q(s, ·) for the learner's current discretized state.

The transition from one to the other is a single threshold check on completed-session count —
see `active_policy` below. It is intentionally the *only* place that decision is made, so the
regime a user is in is always unambiguous and logged.

Critically, the Q-table is updated from *every* real transition regardless of which policy chose
the action (Q-learning is off-policy). So cold-start sessions aren't wasted — they're already
warming up the Q-table before Q-learning ever gets to choose anything itself.
"""

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.rl_transition import RLTransition
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User
from app.rl import bandit, qlearning
from app.rl.actions import IMPLEMENTED_MODES
from app.rl.reward import compute_learning_reward, is_topic_mastered
from app.rl.state import LearnerState, compute_state
from app.telemetry.scoring import compute_engagement_score

logger = logging.getLogger("app.rl.policy")

POLICY_COLD_START = "cold_start_thompson"
POLICY_Q_LEARNING = "q_learning"


@dataclass(frozen=True)
class ActionDecision:
    mode: str
    policy: str
    epsilon: float | None
    state: LearnerState
    action_scores: dict[str, float]


def completed_session_count(db: Session, user_id: str) -> int:
    return db.query(LearningSession).filter_by(user_id=user_id, status="completed").count()


def active_policy(db: Session, user_id: str) -> str:
    threshold = get_settings().rl_cold_start_session_threshold
    return POLICY_COLD_START if completed_session_count(db, user_id) < threshold else POLICY_Q_LEARNING


def choose_action(db: Session, user: User, chat: Chat) -> ActionDecision:
    """Advisory action selection — drives the "Suggested for you" UI and the alternatives
    offered by the "still with it?" check-in. Not binding: the learner can (and often will) pick
    a different format manually, which is fine — see the module docstring on off-policy
    learning."""
    state = compute_state(db, user, chat)
    policy = active_policy(db, user.id)

    if policy == POLICY_COLD_START:
        mode, _confidence, scores = bandit.suggest(db, user.id, modes=IMPLEMENTED_MODES)
        logger.info("policy=cold_start user=%s state=%s action=%s", user.id, state.key, mode)
        return ActionDecision(mode=mode, policy=policy, epsilon=None, state=state, action_scores=scores)

    mode, epsilon, q_values = qlearning.select_action(db, user.id, state.key, IMPLEMENTED_MODES)
    logger.info(
        "policy=q_learning user=%s state=%s action=%s epsilon=%.3f", user.id, state.key, mode, epsilon
    )
    return ActionDecision(mode=mode, policy=policy, epsilon=epsilon, state=state, action_scores=q_values)


def snapshot_decision(db: Session, user: User, chat: Chat, mode: str) -> dict:
    """Called at session creation (app/sessions/router.py::create_session) — records the MDP
    context for whatever action is actually being taken, which may or may not be what
    `choose_action` would have suggested (the learner is always free to pick manually). This is
    the `state`/`action` half of the (state, action, reward, next_state, done) transition; the
    other half is filled in by `record_outcome` once the session completes."""
    state = compute_state(db, user, chat)
    policy = active_policy(db, user.id)
    epsilon = qlearning.current_epsilon(db, user.id) if policy == POLICY_Q_LEARNING else None
    logger.info(
        "decision_snapshot user=%s chat=%s state=%s action=%s policy=%s", user.id, chat.id, state.key, mode, policy
    )
    return {
        "rl_state_key": state.key,
        "rl_state_json": state.as_dict(),
        "rl_action": mode,
        "rl_policy": policy,
        "rl_epsilon": epsilon,
    }


def record_outcome(db: Session, session: LearningSession) -> tuple[float, dict]:
    """Called at session completion (app/sessions/router.py::complete_session). Computes the
    learning reward, the resulting next state, whether this transition ends its episode, then
    performs the actual Q-learning update — the closing half of the (state, action, reward,
    next_state, done) transition opened by `snapshot_decision`.

    Returns (engagement_score, bandit_params) to keep the existing `/sessions/{id}/complete`
    response shape (bandit_params kept for backward compatibility / the legacy stats display —
    see app/stats/aggregation.py)."""
    user = db.get(User, session.user_id)
    content = db.get(GeneratedContent, session.generated_content_id)
    chat = db.get(Chat, content.chat_id) if content else None

    engagement_score = compute_engagement_score(db, session)
    session.engagement_score = engagement_score
    db.commit()

    events = db.query(TelemetryEvent).filter(TelemetryEvent.session_id == session.id).all()
    reward = compute_learning_reward(db, session, events)
    done = is_topic_mastered(db, session, events, engagement_score)

    # Legacy Thompson stats — kept updated regardless of which policy is currently choosing
    # actions, both for continuity of the cold-start posterior and because the stats dashboard
    # still shows it as a secondary/legacy signal (see app/stats/aggregation.py).
    action = session.rl_action or (content.mode if content else None)
    bandit_params = bandit.update(db, session.user_id, action, reward) if action else {}

    if user is None or chat is None or action is None:
        # Nothing sensible to compute a next-state/transition for (shouldn't happen in practice
        # for a real session, but fail soft rather than 500 the completion endpoint over it).
        logger.warning("record_outcome: missing user/chat/action for session=%s — skipping RL update", session.id)
        return engagement_score, bandit_params

    next_state = compute_state(db, user, chat)
    state_key = session.rl_state_key or next_state.key
    state_json = session.rl_state_json or next_state.as_dict()
    policy = session.rl_policy or active_policy(db, user.id)

    new_q = qlearning.update_q(
        db,
        user_id=user.id,
        state_key=state_key,
        action=action,
        reward=reward,
        next_state_key=next_state.key,
        done=done,
    )

    db.add(
        RLTransition(
            user_id=user.id,
            chat_id=chat.id,
            session_id=session.id,
            state_key=state_key,
            state_json=state_json,
            action=action,
            reward=reward,
            next_state_key=next_state.key,
            next_state_json=next_state.as_dict(),
            done=done,
            policy=policy,
            epsilon=session.rl_epsilon,
        )
    )
    db.commit()

    logger.info(
        "transition_recorded user=%s chat=%s session=%s state=%s action=%s reward=%.4f "
        "next_state=%s done=%s policy=%s new_q=%.4f",
        user.id,
        chat.id,
        session.id,
        state_key,
        action,
        reward,
        next_state.key,
        done,
        policy,
        new_q,
    )

    return engagement_score, bandit_params
