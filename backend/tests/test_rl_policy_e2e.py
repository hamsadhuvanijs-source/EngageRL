from app.config import get_settings
from app.models.q_state import QState
from app.models.rl_transition import RLTransition
from app.rl import qlearning
from app.rl.policy import (
    POLICY_COLD_START,
    POLICY_Q_LEARNING,
    active_policy,
    choose_action,
    record_outcome,
    snapshot_decision,
)
from tests.factories import add_event, make_chat, make_content, make_session, make_user


def test_new_user_starts_in_cold_start_regime(db):
    user = make_user(db)
    assert active_policy(db, user.id) == POLICY_COLD_START


def test_regime_switches_to_q_learning_after_threshold_completed_sessions(db, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_cold_start_session_threshold", 2)

    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")

    assert active_policy(db, user.id) == POLICY_COLD_START
    make_session(db, user, content, status="completed")
    assert active_policy(db, user.id) == POLICY_COLD_START
    make_session(db, user, content, status="completed")
    assert active_policy(db, user.id) == POLICY_Q_LEARNING


def test_choose_action_never_crashes_for_a_brand_new_user_and_returns_an_implemented_mode(db):
    from app.rl.actions import IMPLEMENTED_MODES

    user = make_user(db)
    chat = make_chat(db, user)

    decision = choose_action(db, user, chat)
    assert decision.policy == POLICY_COLD_START
    assert decision.mode in IMPLEMENTED_MODES


def test_full_transition_lifecycle_snapshot_then_record_outcome(db, monkeypatch):
    """The actual end-to-end loop: State -> Action -> Interaction -> Reward -> Next State ->
    Q-update, exercised through the real entry points sessions/router.py calls."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_cold_start_session_threshold", 0)  # force Q-learning immediately

    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")

    decision = choose_action(db, user, chat)
    assert decision.policy == POLICY_Q_LEARNING

    session = make_session(db, user, content, status="active", engagement_score=None)
    for key, value in snapshot_decision(db, user, chat, content.mode).items():
        setattr(session, key, value)
    db.commit()

    assert session.rl_state_key is not None
    assert session.rl_action == "quiz"
    assert session.rl_policy == POLICY_Q_LEARNING

    add_event(db, session, "dwell", {"seconds": 60})
    for i in range(5):
        add_event(db, session, "quiz_answer", {"question_index": i, "correct": True})
        add_event(db, session, "progress", {"ratio": (i + 1) / 5})
    session.status = "completed"
    db.commit()

    engagement_score, bandit_params = record_outcome(db, session)
    assert 0.0 <= engagement_score <= 1.0
    assert bandit_params  # legacy stats still updated

    transition = db.query(RLTransition).filter_by(session_id=session.id).one()
    assert transition.state_key == session.rl_state_key
    assert transition.action == "quiz"
    assert 0.0 <= transition.reward <= 1.0
    assert transition.next_state_key  # computed, not left blank
    assert transition.done is True  # full progress + perfect accuracy + high engagement

    q_row = db.query(QState).filter_by(user_id=user.id, state_key=session.rl_state_key, action="quiz").one()
    assert q_row.q_value > 0.0  # moved off the zero-init toward the positive reward
    assert q_row.update_count == 1


def test_choose_action_scores_stay_bounded_even_once_raw_q_value_exceeds_one(db, monkeypatch):
    """A (state, action) pair repeatedly bootstrapped through non-terminal transitions
    legitimately pushes its raw Q-value above 1 (it's a discounted sum of future rewards, not a
    single-step one) — but SuggestModeOut.confidence and the "still with it?" alternatives are
    displayed as 0-1 percentages. choose_action's action_scores (blended_q_values under the hood
    — see qlearning.blended_q_values) must stay on that reward-like [0, 1] scale regardless, or
    every well-visited action would show as a flat, meaningless 100%."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_cold_start_session_threshold", 0)
    monkeypatch.setattr(settings, "rl_gamma", 0.9)

    user = make_user(db)
    chat = make_chat(db, user)

    # Repeatedly bootstrap the same (state, action) pair through non-terminal transitions with a
    # solid-but-unremarkable reward, so it converges toward its steady state Q* = r/(1-gamma).
    for _ in range(50):
        qlearning.update_q(db, user.id, state_key="s1", action="quiz", reward=0.6, next_state_key="s1", done=False)

    raw_q = qlearning.get_q_value(db, user.id, "s1", "quiz")
    assert raw_q > 1.0  # confirms the scenario: the raw Q-value really did cross the reward's own scale

    decision = choose_action(db, user, chat)
    assert all(0.0 <= v <= 1.0 for v in decision.action_scores.values())


def test_blended_q_values_shrinks_a_single_sample_toward_the_prior(db, monkeypatch):
    """The core confidence-shrinkage property: a (state, action) pair visited exactly once must
    not be trusted as much as the prior it's blended against — with pseudo_count=3, a single
    observation should count for 1 part in 4 of the final estimate, not dominate it outright."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_gamma", 0.9)
    user = make_user(db)

    qlearning.update_q(db, user.id, state_key="s1", action="quiz", reward=1.0, next_state_key="s1", done=True)
    # raw_q == 1.0 (first-ever visit, see test_update_q_terminal_transition_uses_reward_only) ->
    # q_to_reward_scale(1.0) = 1.0 * (1 - 0.9) = 0.1
    blended = qlearning.blended_q_values(
        db, user.id, "s1", prior_by_action={"quiz": 0.5}, actions=("quiz",), pseudo_count=3.0
    )
    # (n=1 * 0.1 + k=3 * 0.5) / (1 + 3) = (0.1 + 1.5) / 4 = 0.4
    assert blended["quiz"] == 0.4


def test_blended_q_values_falls_back_entirely_to_the_prior_when_never_visited(db):
    """n=0 (this exact state/action pair never observed) must collapse to the prior outright —
    "no evidence yet" is a different thing from "known bad" (which zero-init raw Q would imply)."""
    user = make_user(db)
    blended = qlearning.blended_q_values(
        db, user.id, "never-seen-state", prior_by_action={"quiz": 0.73}, actions=("quiz",)
    )
    assert blended["quiz"] == 0.73


def test_off_policy_learning_from_a_manually_chosen_action(db, monkeypatch):
    """Q-learning is off-policy: even a cold-start-chosen (or freely user-chosen) action must
    still produce a valid, real transition and Q-update — the update doesn't require the action
    to have come from qlearning.select_action itself."""
    settings = get_settings()
    monkeypatch.setattr(settings, "rl_cold_start_session_threshold", 100)  # stay in cold start

    user = make_user(db)
    chat = make_chat(db, user)
    # User manually picks "video" even though nothing suggested it.
    content = make_content(db, chat, mode="video", content_json={"video_url": "/x.mp4", "scenes": []})

    session = make_session(db, user, content, status="active", engagement_score=None)
    for key, value in snapshot_decision(db, user, chat, content.mode).items():
        setattr(session, key, value)
    db.commit()
    assert session.rl_policy == POLICY_COLD_START

    add_event(db, session, "dwell", {"seconds": 30})
    add_event(db, session, "progress", {"ratio": 1.0})
    session.status = "completed"
    db.commit()

    record_outcome(db, session)

    q_row = db.query(QState).filter_by(user_id=user.id, state_key=session.rl_state_key, action="video").one_or_none()
    assert q_row is not None  # the Q-table learned from this transition despite the cold-start regime
