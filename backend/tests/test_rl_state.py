from app.rl.state import (
    NONE_LABEL,
    LearnerState,
    _bucket3,
    _last_mode_in_topic,
    _pace_level,
    compute_state,
    parse_state_key,
)
from tests.factories import add_event, make_chat, make_content, make_session, make_user


def test_bucket3_boundaries():
    assert _bucket3(0.0, 0.4, 0.7, ("low", "medium", "high")) == "low"
    assert _bucket3(0.4, 0.4, 0.7, ("low", "medium", "high")) == "low"  # low_max is inclusive
    assert _bucket3(0.41, 0.4, 0.7, ("low", "medium", "high")) == "medium"
    assert _bucket3(0.7, 0.4, 0.7, ("low", "medium", "high")) == "high"  # high_min is inclusive
    assert _bucket3(1.0, 0.4, 0.7, ("low", "medium", "high")) == "high"


def test_pace_level_thresholds():
    assert _pace_level(None) == "fast"  # default multiplier 1.0

    class FakeUser:
        reading_pace_multiplier = 1.05

    assert _pace_level(FakeUser()) == "fast"
    FakeUser.reading_pace_multiplier = 1.5
    assert _pace_level(FakeUser()) == "normal"
    FakeUser.reading_pace_multiplier = 2.0
    assert _pace_level(FakeUser()) == "slow"


def test_state_key_is_deterministic_and_sorted():
    state = LearnerState(
        engagement="high", progress="low", pace="normal", quiz_accuracy=NONE_LABEL, last_mode="quiz", content_length="short"
    )
    key = state.key
    # Sorted alphabetically by feature name regardless of dataclass field order.
    assert key == (
        "content_length=short|engagement=high|last_mode=quiz|pace=normal|progress=low|quiz_accuracy=none"
    )


def test_parse_state_key_roundtrips():
    state = LearnerState(
        engagement="medium", progress="high", pace="slow", quiz_accuracy="high", last_mode="video", content_length="long"
    )
    assert parse_state_key(state.key) == state.as_dict()


def test_compute_state_defaults_for_brand_new_user(db):
    user = make_user(db)
    chat = make_chat(db, user)

    state = compute_state(db, user, chat)

    # No history at all yet — everything should fall back to a sensible neutral default rather
    # than crashing or defaulting to an extreme (e.g. "low" everywhere would unfairly punish a
    # user we simply know nothing about yet).
    assert state.engagement == "medium"
    assert state.progress == "medium"
    assert state.pace == "fast"  # multiplier starts at 1.0
    assert state.quiz_accuracy == NONE_LABEL
    assert state.last_mode == NONE_LABEL
    assert state.content_length == "short"  # no sources -> 0 chars -> short bucket


def test_last_mode_is_scoped_to_the_current_chat_not_global(db):
    user = make_user(db)
    chat_a = make_chat(db, user, title="Topic A")
    chat_b = make_chat(db, user, title="Topic B")

    content_a = make_content(db, chat_a, mode="video")
    make_session(db, user, content_a, status="completed")

    # A completed session exists for chat_a but chat_b has none yet — last_mode for chat_b must
    # not leak chat_a's history, since it's meant to be this episode's own recent format history.
    assert _last_mode_in_topic(db, user.id, chat_b.id) == NONE_LABEL
    assert _last_mode_in_topic(db, user.id, chat_a.id) == "video"


def test_quiz_accuracy_level_from_real_quiz_answer_events(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="quiz")
    session = make_session(db, user, content, status="completed")

    for i in range(4):
        add_event(db, session, "quiz_answer", {"question_index": i, "correct": i < 3})  # 3/4 correct = 0.75

    state = compute_state(db, user, chat)
    assert state.quiz_accuracy == "medium"  # 0.75 is between ACCURACY_LOW_MAX=0.5 and HIGH_MIN=0.8


def test_qa_mode_does_not_contribute_to_quiz_accuracy(db):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="qa", content_json={"items": [{"question": "q", "answer": "a"}]})
    session = make_session(db, user, content, status="completed")
    # QA has no correctness concept, but even if a stray quiz_answer-shaped event showed up, QA
    # sessions shouldn't be counted as quiz accuracy history.
    add_event(db, session, "quiz_answer", {"question_index": 0, "correct": True})

    state = compute_state(db, user, chat)
    assert state.quiz_accuracy == NONE_LABEL
