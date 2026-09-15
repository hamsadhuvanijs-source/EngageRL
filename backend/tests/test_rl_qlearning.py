import random

from app.config import get_settings
from app.rl import qlearning
from tests.factories import make_user


def test_get_q_value_defaults_to_zero_for_unseen_state_action(db):
    user = make_user(db)
    assert qlearning.get_q_value(db, user.id, "some-state-never-seen", "quiz") == 0.0


def test_get_q_values_zero_initializes_every_action(db):
    user = make_user(db)
    values = qlearning.get_q_values(db, user.id, "unseen-state", actions=("quiz", "video"))
    assert values == {"quiz": 0.0, "video": 0.0}


def test_update_q_terminal_transition_uses_reward_only(db, monkeypatch):
    user = make_user(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_alpha", 0.5)

    new_q = qlearning.update_q(
        db, user.id, state_key="s1", action="quiz", reward=0.8, next_state_key="s2", done=True
    )
    # First-ever visit: effective_alpha = max(0.5, 1/(0+1)) = 1.0, so Q lands exactly on the
    # observed reward rather than being diluted toward 0 — see update_q's docstring.
    assert new_q == 0.8
    assert qlearning.get_q_value(db, user.id, "s1", "quiz") == 0.8


def test_update_q_learning_rate_blends_toward_configured_alpha_as_visits_accumulate(db, monkeypatch):
    user = make_user(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_alpha", 0.1)

    # 1st visit: effective_alpha = max(0.1, 1/1) = 1.0 -> Q = 0 + 1.0*(1.0-0) = 1.0
    q1 = qlearning.update_q(db, user.id, "s1", "quiz", reward=1.0, next_state_key="s1", done=True)
    assert q1 == 1.0

    # 2nd visit: effective_alpha = max(0.1, 1/2) = 0.5 -> Q = 1.0 + 0.5*(0.0-1.0) = 0.5
    q2 = qlearning.update_q(db, user.id, "s1", "quiz", reward=0.0, next_state_key="s1", done=True)
    assert q2 == 0.5

    # By the 11th visit, 1/(10+1) < 0.1, so the configured floor alpha=0.1 takes back over —
    # confirms it doesn't decay to an ever-shrinking rate forever.
    for _ in range(9):
        qlearning.update_q(db, user.id, "s1", "quiz", reward=0.0, next_state_key="s1", done=True)
    q_before = qlearning.get_q_value(db, user.id, "s1", "quiz")
    q_after = qlearning.update_q(db, user.id, "s1", "quiz", reward=1.0, next_state_key="s1", done=True)
    assert q_after == q_before + 0.1 * (1.0 - q_before)


def test_update_q_non_terminal_bootstraps_off_next_state_max(db, monkeypatch):
    user = make_user(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_alpha", 1.0)  # full update, easiest to hand-check
    monkeypatch.setattr(settings, "rl_gamma", 0.5)

    # Seed the next state with a known best action value.
    qlearning.update_q(db, user.id, state_key="s2", action="video", reward=1.0, next_state_key="s2", done=True)
    assert qlearning.get_q_value(db, user.id, "s2", "video") == 1.0

    new_q = qlearning.update_q(
        db, user.id, state_key="s1", action="quiz", reward=0.2, next_state_key="s2", done=False
    )
    # target = reward + gamma * max_a' Q(s2, a') = 0.2 + 0.5 * 1.0 = 0.7; alpha=1.0 -> Q = 0.7
    assert new_q == 0.7


def test_update_q_persists_across_calls_and_increments_visit_count(db):
    user = make_user(db)
    qlearning.update_q(db, user.id, "s1", "quiz", reward=0.5, next_state_key="s1", done=True)
    qlearning.update_q(db, user.id, "s1", "quiz", reward=0.5, next_state_key="s1", done=True)

    from app.models.q_state import QState

    row = db.query(QState).filter_by(user_id=user.id, state_key="s1", action="quiz").one()
    assert row.update_count == 2


def test_select_action_pure_exploit_picks_the_max_q_action(db, monkeypatch):
    user = make_user(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_epsilon_start", 0.0)
    monkeypatch.setattr(settings, "rl_epsilon_min", 0.0)

    qlearning.update_q(db, user.id, "s1", "quiz", reward=0.9, next_state_key="s1", done=True)
    qlearning.update_q(db, user.id, "s1", "video", reward=0.1, next_state_key="s1", done=True)

    action, epsilon, q_values = qlearning.select_action(db, user.id, "s1", actions=("quiz", "video"))
    assert epsilon == 0.0
    assert action == "quiz"
    assert q_values["quiz"] > q_values["video"]


def test_select_action_pure_explore_can_pick_a_lower_value_action(db, monkeypatch):
    user = make_user(db)
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_epsilon_start", 1.0)
    monkeypatch.setattr(settings, "rl_epsilon_min", 1.0)
    monkeypatch.setattr(settings, "rl_epsilon_decay", 1.0)  # never decays below 1.0 either

    qlearning.update_q(db, user.id, "s1", "quiz", reward=0.9, next_state_key="s1", done=True)
    qlearning.update_q(db, user.id, "s1", "video", reward=0.1, next_state_key="s1", done=True)

    random.seed(0)
    picks = {qlearning.select_action(db, user.id, "s1", actions=("quiz", "video"))[0] for _ in range(30)}
    # With epsilon=1.0 every pick is uniform-random over both actions — across 30 draws we should
    # see the lower-value action chosen at least once (this would fail if selection quietly
    # ignored epsilon and always exploited).
    assert picks == {"quiz", "video"}


def test_select_action_never_crashes_on_a_brand_new_unseen_state(db):
    """New users / never-before-seen states must be handled gracefully — all-zero Q(s,·) still
    produces a valid action choice instead of raising."""
    user = make_user(db)
    action, epsilon, q_values = qlearning.select_action(db, user.id, "totally-new-state")
    assert action in q_values
    assert all(v == 0.0 for v in q_values.values())


def test_q_to_reward_scale_converts_discounted_q_back_onto_the_reward_scale(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_gamma", 0.9)

    # A (state, action) pair repeatedly revisited with a constant reward r converges toward the
    # fixed point Q* = r / (1 - gamma) — e.g. reward=0.5 -> Q*=5.0 under gamma=0.9. Displaying
    # that raw Q-value as a clamped 0-1 percentage would saturate at 100% for almost any decent
    # action; q_to_reward_scale must invert the discounting back to ~the original reward.
    steady_state_q = 0.5 / (1 - 0.9)
    assert qlearning.q_to_reward_scale(steady_state_q) == 0.5


def test_epsilon_decays_with_q_learning_experience_and_floors_at_minimum(db):
    user = make_user(db)
    settings = get_settings()

    from app.models.rl_transition import RLTransition

    e0 = qlearning.current_epsilon(db, user.id)
    assert e0 == settings.rl_epsilon_start

    for _ in range(200):
        db.add(
            RLTransition(
                user_id=user.id,
                chat_id="chat-x",
                session_id=f"session-{_}",
                state_key="s",
                state_json={},
                action="quiz",
                reward=0.5,
                next_state_key="s",
                next_state_json={},
                done=True,
                policy="q_learning",
            )
        )
    db.commit()

    e_after = qlearning.current_epsilon(db, user.id)
    assert e_after == settings.rl_epsilon_min
    assert e_after < e0
