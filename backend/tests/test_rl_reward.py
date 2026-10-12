from app.rl.reward import (
    MASTERY_ACCURACY_THRESHOLD,
    MASTERY_ENGAGEMENT_THRESHOLD,
    MASTERY_PROGRESS_THRESHOLD,
    compute_learning_reward,
    is_topic_mastered,
)
from tests.factories import add_event, make_chat, make_content, make_session, make_user


def test_reward_rewards_quiz_accuracy_on_top_of_engagement(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")

    from app.models.telemetry_event import TelemetryEvent

    good_session = make_session(db, user, content, status="completed")
    add_event(db, good_session, "dwell", {"seconds": 60})
    for i in range(5):
        add_event(db, good_session, "quiz_answer", {"question_index": i, "correct": True})
        add_event(db, good_session, "progress", {"ratio": (i + 1) / 5})
    good_events = db.query(TelemetryEvent).filter_by(session_id=good_session.id).all()
    good_reward = compute_learning_reward(db, good_session, good_events)

    bad_session = make_session(db, user, content, status="completed")
    add_event(db, bad_session, "dwell", {"seconds": 60})
    for i in range(5):
        add_event(db, bad_session, "quiz_answer", {"question_index": i, "correct": False})
        add_event(db, bad_session, "progress", {"ratio": (i + 1) / 5})
    bad_events = db.query(TelemetryEvent).filter_by(session_id=bad_session.id).all()
    bad_reward = compute_learning_reward(db, bad_session, bad_events)

    assert good_reward > bad_reward


def test_reward_does_not_reward_dwelling_longer_with_no_extra_progress(db):
    """The core "don't just reward spending more time" requirement — two sessions with
    identical progress/interaction but very different dwell time should not have the longer one
    score meaningfully higher (the underlying engagement score already caps/decays excess
    dwell; this asserts the RL reward doesn't undo that by weighting raw time some other way)."""
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="summary", content_json={"summary": "x" * 300})

    normal_session = make_session(db, user, content, status="completed")
    add_event(db, normal_session, "dwell", {"seconds": 20})
    add_event(db, normal_session, "click", {})

    from app.models.telemetry_event import TelemetryEvent

    normal_events = db.query(TelemetryEvent).filter_by(session_id=normal_session.id).all()
    normal_reward = compute_learning_reward(db, normal_session, normal_events)

    dawdling_session = make_session(db, user, content, status="completed")
    add_event(db, dawdling_session, "dwell", {"seconds": 20 * 20})  # 20x longer, no more interaction
    add_event(db, dawdling_session, "click", {})

    dawdling_events = db.query(TelemetryEvent).filter_by(session_id=dawdling_session.id).all()
    dawdling_reward = compute_learning_reward(db, dawdling_session, dawdling_events)

    assert dawdling_reward <= normal_reward


def test_reward_is_bounded_0_to_1(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="completed")
    for i in range(5):
        add_event(db, session, "quiz_answer", {"question_index": i, "correct": True})
        add_event(db, session, "progress", {"ratio": 1.0})
    add_event(db, session, "dwell", {"seconds": 175})

    from app.models.telemetry_event import TelemetryEvent

    events = db.query(TelemetryEvent).filter_by(session_id=session.id).all()
    reward = compute_learning_reward(db, session, events)
    assert 0.0 <= reward <= 1.0


def test_is_topic_mastered_requires_completed_status(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="active", engagement_score=None)
    assert is_topic_mastered(db, session, [], 0.95) is False


def test_is_topic_mastered_requires_high_progress_when_progress_is_tracked(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="completed")
    events = [add_event(db, session, "progress", {"ratio": MASTERY_PROGRESS_THRESHOLD - 0.1})]
    assert is_topic_mastered(db, session, events, MASTERY_ENGAGEMENT_THRESHOLD + 0.1) is False


def test_is_topic_mastered_requires_quiz_accuracy_for_quiz_mode(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="completed")
    events = [
        add_event(db, session, "progress", {"ratio": MASTERY_PROGRESS_THRESHOLD}),
        add_event(db, session, "quiz_answer", {"question_index": 0, "correct": False}),
        add_event(db, session, "quiz_answer", {"question_index": 1, "correct": False}),
    ]
    assert is_topic_mastered(db, session, events, MASTERY_ENGAGEMENT_THRESHOLD + 0.1) is False


def test_is_topic_mastered_true_when_all_signals_clear(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="completed")
    events = [
        add_event(db, session, "progress", {"ratio": 1.0}),
        add_event(db, session, "quiz_answer", {"question_index": 0, "correct": True}),
        add_event(db, session, "quiz_answer", {"question_index": 1, "correct": True}),
    ]
    assert is_topic_mastered(db, session, events, MASTERY_ENGAGEMENT_THRESHOLD + 0.1) is True
    assert MASTERY_ACCURACY_THRESHOLD <= 1.0  # sanity: constant is a valid fraction
