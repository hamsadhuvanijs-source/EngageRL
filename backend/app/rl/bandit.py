"""Thompson-sampling multi-armed bandit — COLD-START POLICY ONLY.

This is no longer the system's main personalization policy. It exists purely to make
reasonable action choices during a user's first few sessions, before there is enough history
for the Q-learning policy's per-state action-values to mean anything (an empty/near-empty
Q-table would otherwise tie-break arbitrarily instead of exploring sensibly). See
`app/rl/policy.py` for the hybrid orchestration and `app/rl/qlearning.py` for the actual
long-term MDP-based policy that takes over once `COLD_START_SESSION_THRESHOLD` (app/config.py)
completed sessions exist for a user.

Every action chosen here — cold-start or not — still gets its real outcome recorded as a
(state, action, reward, next_state, done) transition and folded into the Q-table (Q-learning is
off-policy: it can learn from any action that was actually taken, not just ones it chose
itself). So by the time cold start ends, the Q-table already has real experience to work from
instead of starting completely blank.
"""

import random

from sqlalchemy.orm import Session

from app.models.bandit_state import BanditState
from app.rl.actions import IMPLEMENTED_MODES

ALL_MODES = IMPLEMENTED_MODES


def get_or_create_state(db: Session, user_id: str, mode: str) -> BanditState:
    state = db.query(BanditState).filter_by(user_id=user_id, mode=mode).one_or_none()
    if state is None:
        state = BanditState(user_id=user_id, mode=mode, params_json={"alpha": 1.0, "beta": 1.0})
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def suggest(db: Session, user_id: str, modes: tuple[str, ...] = ALL_MODES) -> tuple[str, float, dict[str, float]]:
    """Thompson sampling over independent Beta(alpha, beta) per (user, mode) — the cold-start
    explore/exploit decision, used only while `app/rl/policy.py` judges a user to still be in
    cold start (see `COLD_START_SESSION_THRESHOLD`). Each mode gets one random draw from its
    own posterior, and the highest draw wins. That randomness is *why* under-tried modes still
    occasionally get a chance (exploration) instead of the system permanently locking onto
    whatever won first.

    The score returned per mode is deliberately NOT that random draw — a draw is re-rolled on
    every call, so displaying it made the same mode's "confidence" visibly jump around between
    page loads with zero new data, which reads as fake even though the reward history behind it
    is real. Instead we return each mode's posterior mean alpha / (alpha + beta): the actual,
    deterministic, data-derived estimate of how engaging that mode has been, computed straight
    from accumulated real session scores (see rl/hooks.py -> telemetry/scoring.py). It only
    moves when a real session completes and feeds a new reward in."""
    draws: dict[str, float] = {}
    means: dict[str, float] = {}
    for mode in modes:
        state = get_or_create_state(db, user_id, mode)
        alpha = float(state.params_json.get("alpha", 1.0))
        beta = float(state.params_json.get("beta", 1.0))
        draws[mode] = random.betavariate(alpha, beta)
        means[mode] = alpha / (alpha + beta)

    best_mode = max(draws, key=draws.get)
    return best_mode, means[best_mode], means


def update(db: Session, user_id: str, mode: str, reward: float) -> dict:
    """Beta-Bernoulli update using the continuous engagement score as a pseudo-count:
    alpha += reward, beta += (1 - reward)."""
    reward = max(0.0, min(1.0, reward))
    state = get_or_create_state(db, user_id, mode)
    alpha = float(state.params_json.get("alpha", 1.0)) + reward
    beta = float(state.params_json.get("beta", 1.0)) + (1.0 - reward)
    state.params_json = {"alpha": alpha, "beta": beta}
    db.commit()
    db.refresh(state)
    return state.params_json
