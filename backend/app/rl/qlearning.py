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


def q_to_reward_scale(q_value: float) -> float:
    """Converts a raw Q-value onto the same ~[0, 1] scale as the rewards it's built from, for
    display purposes only (action *selection* is scale-invariant — comparing raw Q(s, ·) picks
    the same best action either way, so select_action/update_q never need this).

    Q(s, a) is a *discounted sum of future rewards*, not a single-step quantity — for a
    (state, action) pair that keeps getting revisited with a roughly constant reward r, it
    converges toward the fixed point r / (1 - gamma), not toward r itself. With the default
    gamma=0.9 that's up to 10x the reward scale, so displaying a raw Q-value as a clamped 0-1
    "confidence"/"preference" percentage saturates at 100% almost immediately and stops
    reflecting real differences in how well an action is doing. Multiplying by (1 - gamma)
    inverts that geometric series back to the steady-state average per-step reward it
    represents, which is the same [0, 1]-ish scale as the reward and the cold-start Thompson
    mean it's displayed alongside."""
    settings = get_settings()
    return q_value * (1.0 - settings.rl_gamma)


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


def epsilon_greedy_pick(values: dict[str, float], epsilon: float, actions: tuple[str, ...]) -> str:
    """The explore/exploit decision given any per-action value mapping — factored out of
    select_action so policy.py's confidence-shrunk selection (see blended_q_values) can go
    through the exact same random-explore-or-argmax-with-random-tie-break behavior over its own
    blended values, instead of duplicating it. Ties for the greedy action are broken randomly
    rather than always favoring the first action in `actions`, so an untouched, all-equal value
    mapping explores uniformly instead of always picking the same default action."""
    if random.random() < epsilon:
        return random.choice(actions)
    best_value = max(values.values())
    best_actions = [a for a, v in values.items() if v == best_value]
    return random.choice(best_actions)


def select_action(
    db: Session, user_id: str, state_key: str, actions: tuple[str, ...] = IMPLEMENTED_MODES
) -> tuple[str, float, dict[str, float]]:
    """Epsilon-greedy selection over raw Q(s, ·). Returns (chosen_action, epsilon_used, q_values).
    Kept as a direct, self-contained entry point over the raw table (e.g. for tests/inspection);
    policy.py's live action selection goes through blended_q_values + epsilon_greedy_pick instead
    — see that function's docstring for why."""
    epsilon = current_epsilon(db, user_id)
    q_values = get_q_values(db, user_id, state_key, actions)
    action = epsilon_greedy_pick(q_values, epsilon, actions)
    logger.debug("q_learning select: state=%s action=%s epsilon=%.3f q=%s", state_key, action, epsilon, q_values)
    return action, epsilon, q_values


def blended_q_values(
    db: Session,
    user_id: str,
    state_key: str,
    prior_by_action: dict[str, float],
    actions: tuple[str, ...] = IMPLEMENTED_MODES,
    pseudo_count: float | None = None,
) -> dict[str, float]:
    """Confidence-shrunk Q(s, ·), already on the reward-like [0, 1] scale (see q_to_reward_scale)
    rather than raw Q — this is what actual action selection and display should use, not the raw
    per-state table directly.

    The per-state Q-table is enormous relative to how many sessions one real user generates
    (roughly 3*3*3*4*9*3 = 2916 states x 8 actions — see app/rl/state.py's cardinality note), so
    the overwhelming majority of (state, action) cells only ever get a single sample early on.
    Trusting that single sample outright makes both the choice of action and the displayed
    confidence far noisier than the data actually supports — an all-zero Q for a never-tried
    action in this exact state reads as "known bad" when it's really "no evidence yet", and a
    single lucky/unlucky session can look like a confident preference.

    Shrinks each action's state-specific estimate toward `prior_by_action[action]` — meant to be
    the cold-start bandit's per-mode posterior mean (app/rl/bandit.py), which pools evidence
    across every state that mode has ever been used in and so is far better-sampled than any one
    state cell — weighted by how many times this exact (state, action) pair has actually been
    observed:

        blended(s, a) = (n * q_to_reward_scale(raw_q(s, a)) + k * prior(a)) / (n + k)

    n=0 (never visited in this exact state) collapses to the prior outright — a meaningfully
    better default than zero-init, since "untried here" isn't evidence of being bad, just absence
    of state-specific evidence. As n grows, the state-specific estimate takes back over — same
    spirit as update_q's hybrid learning rate (see its docstring)."""
    settings = get_settings()
    k = pseudo_count if pseudo_count is not None else settings.rl_shrinkage_pseudo_count
    rows = {
        row.action: (row.q_value, row.update_count)
        for row in db.query(QState).filter_by(user_id=user_id, state_key=state_key).all()
    }
    blended: dict[str, float] = {}
    for action in actions:
        raw_q, n = rows.get(action, (0.0, 0))
        state_estimate = q_to_reward_scale(raw_q)
        prior = prior_by_action.get(action, 0.5)
        blended[action] = (n * state_estimate + k * prior) / (n + k)
    return blended


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
