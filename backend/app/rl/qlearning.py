"""Tabular Q-learning core: Q-table access, the Bellman update, and epsilon-greedy selection.

This is the actual long-term MDP policy — NOT a contextual bandit. Actions are chosen from
Q(s, ·) over the explicit discretized learner state `s` (app/rl/state.py), and updated with the
standard tabular Q-learning rule:

    Q(s, a) <- Q(s, a) + alpha * [reward + gamma * max_a' Q(s', a') - Q(s, a)]

with the bootstrapped `max_a' Q(s', a')` term dropped for terminal transitions (done=True),
per the standard terminal-state handling for episodic Q-learning. The table is persisted in the
`q_state` table (app/models/q_state.py) — process restarts don't lose anything.
"""

import logging
import random

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.q_state import QState
from app.models.rl_transition import RLTransition
from app.rl.actions import IMPLEMENTED_MODES

logger = logging.getLogger("app.rl.qlearning")


def get_q_value(db: Session, user_id: str, state_key: str, action: str) -> float:
    """Zero-initialized for any (state, action) pair never seen before — the standard tabular
    Q-learning default, and how new users / newly-encountered states are handled without any
    special-casing: an empty table just means every action currently looks equally (un)promising
    until real experience updates it."""
    row = db.query(QState).filter_by(user_id=user_id, state_key=state_key, action=action).one_or_none()
    return row.q_value if row else 0.0


def get_q_values(
    db: Session, user_id: str, state_key: str, actions: tuple[str, ...] = IMPLEMENTED_MODES
) -> dict[str, float]:
    rows = {
        row.action: row.q_value
        for row in db.query(QState).filter_by(user_id=user_id, state_key=state_key).all()
    }
    return {action: rows.get(action, 0.0) for action in actions}


def current_epsilon(db: Session, user_id: str) -> float:
    """Decays with the number of transitions the Q-learning policy itself has actually selected
    for this user (cold-start transitions don't count — epsilon only governs Q-learning's own
    explore/exploit choice, and starts fresh once Q-learning takes over from cold start)."""
    settings = get_settings()
    q_learning_transitions = (
        db.query(RLTransition).filter_by(user_id=user_id, policy="q_learning").count()
    )
    epsilon = settings.rl_epsilon_start * (settings.rl_epsilon_decay**q_learning_transitions)
    return max(settings.rl_epsilon_min, epsilon)


def select_action(
    db: Session, user_id: str, state_key: str, actions: tuple[str, ...] = IMPLEMENTED_MODES
) -> tuple[str, float, dict[str, float]]:
    """Epsilon-greedy selection over Q(s, ·). Returns (chosen_action, epsilon_used, q_values).
    Ties for the greedy action are broken randomly rather than always favoring the first action
    in `actions`, so an untouched, all-zero Q(s, ·) explores uniformly instead of always picking
    the same default action."""
    epsilon = current_epsilon(db, user_id)
    q_values = get_q_values(db, user_id, state_key, actions)

    if random.random() < epsilon:
        action = random.choice(actions)
        logger.debug("q_learning explore: state=%s action=%s epsilon=%.3f", state_key, action, epsilon)
        return action, epsilon, q_values

    best_value = max(q_values.values())
    best_actions = [a for a, v in q_values.items() if v == best_value]
    action = random.choice(best_actions)
    logger.debug(
        "q_learning exploit: state=%s action=%s epsilon=%.3f q=%.4f", state_key, action, epsilon, best_value
    )
    return action, epsilon, q_values


def update_q(
    db: Session,
    user_id: str,
    state_key: str,
    action: str,
    reward: float,
    next_state_key: str,
    done: bool,
    actions: tuple[str, ...] = IMPLEMENTED_MODES,
) -> float:
    """The Bellman update. Always runs for every real transition regardless of which policy
    (cold-start Thompson sampling or Q-learning) chose the action — Q-learning is off-policy, so
    it can learn from any action that was actually taken, including ones it didn't pick itself.

    Uses a hybrid learning rate: max(settings.rl_alpha, 1 / (prior_visits + 1)). A pure fixed
    alpha (the textbook choice for a *non-stationary* problem like this one, where a learner's
    habits can genuinely drift over time) makes an all-new (state, action) pair converge to the
    observed reward agonizingly slowly — its first-ever sample only moves Q by alpha, so one
    good 0.7-reward session leaves Q sitting at ~0.1, which reads as "the system thinks this is
    bad" when really it just hasn't seen enough of it yet. The 1/n term makes the first sample
    set Q equal to the observed target outright (like a running average), and the second sample
    still move it substantially — then, once 1/n drops below the configured alpha, the fixed
    rate takes back over so later estimates stay adaptable instead of decaying toward frozen."""
    settings = get_settings()
    row = db.query(QState).filter_by(user_id=user_id, state_key=state_key, action=action).one_or_none()
    current_q = row.q_value if row else 0.0
    prior_visits = row.update_count if row else 0

    if done:
        target = reward
    else:
        next_values = get_q_values(db, user_id, next_state_key, actions)
        target = reward + settings.rl_gamma * max(next_values.values())

    effective_alpha = max(settings.rl_alpha, 1.0 / (prior_visits + 1))
    new_q = current_q + effective_alpha * (target - current_q)

    if row is None:
        row = QState(user_id=user_id, state_key=state_key, action=action, q_value=new_q, update_count=1)
        db.add(row)
    else:
        row.q_value = new_q
        row.update_count += 1
    db.commit()

    logger.info(
        "q_update user=%s state=%s action=%s reward=%.4f done=%s target=%.4f alpha=%.3f q: %.4f -> %.4f (n=%d)",
        user_id,
        state_key,
        action,
        reward,
        done,
        target,
        effective_alpha,
        current_q,
        new_q,
        row.update_count,
    )
    return new_q
