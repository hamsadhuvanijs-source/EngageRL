"""Engagement-score behaviour after the anti-gaming rework.

The through-line: a session where the learner clicked through content without engaging with it
must land in the low band (< ~0.4), and there must be no fixed "floor" that a disengaged session
gets for free (no tab-switching, a stray 🙂, or simply pressing "mark complete").
"""

import app.telemetry.scoring as S
from app.telemetry.scoring import compute_engagement_score
from tests.factories import add_event, make_chat, make_content, make_session, make_user

FLASHCARDS_10 = {"cards": [{"question": f"q{i}", "answer": f"a{i}"} for i in range(10)]}


def _flashcards_session(db, status="completed"):
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(
        db, chat, mode="flashcards", content_json=FLASHCARDS_10, options_json={"difficulty": "medium"}
    )
    return user, make_session(db, user, content, status=status, engagement_score=None)


def test_weights_sum_to_one():
    assert S.WEIGHT_DWELL + S.WEIGHT_DEPTH + S.WEIGHT_COMPLETION + S.WEIGHT_FEEDBACK == 1.0


def test_bare_completed_session_has_no_free_floor(db):
    """Marking a session complete with zero telemetry must not score anywhere near "engaged"."""
    _user, session = _flashcards_session(db)
    assert compute_engagement_score(db, session) < 0.25


def test_click_through_without_reading_scores_low(db):
    """Flashcards: navigated all the way through (dwell accrues, clicks logged) but never
    flipped a card, so no `progress` telemetry. Old model gave ~0.77; must now be low."""
    _user, session = _flashcards_session(db)
    for _ in range(12):
        add_event(db, session, "dwell", {"seconds": 5})
        add_event(db, session, "click", {})
    # no "progress" events at all -> resolve_progress() == 0.0 for a progress-tracked mode
    score = compute_engagement_score(db, session)
    assert score < 0.4, score


def test_attentive_flashcards_session_scores_high(db):
    """Flipped every card (progress -> 1.0), spent roughly the expected time, finished."""
    _user, session = _flashcards_session(db)
    for i in range(10):
        add_event(db, session, "dwell", {"seconds": 12})
        add_event(db, session, "click", {})
        add_event(db, session, "progress", {"ratio": (i + 1) / 10})
    score = compute_engagement_score(db, session)
    assert score > 0.75, score


def test_partial_but_genuine_beats_full_clickthrough(db):
    """Reading half the cards for real should beat clicking through all of them."""
    _u1, genuine = _flashcards_session(db)
    for i in range(5):
        add_event(db, genuine, "dwell", {"seconds": 12})
        add_event(db, genuine, "progress", {"ratio": (i + 1) / 10})

    _u2, clickthrough = _flashcards_session(db)
    for _ in range(15):
        add_event(db, clickthrough, "dwell", {"seconds": 5})
        add_event(db, clickthrough, "click", {})

    assert compute_engagement_score(db, genuine) > compute_engagement_score(db, clickthrough)


def test_enjoyment_yes_does_not_rescue_an_early_bail(db):
    """A reflexive end-of-session 🙂 must not overwrite "not interesting, leaving at 30%"."""
    _user, session = _flashcards_session(db)
    for i in range(3):
        add_event(db, session, "dwell", {"seconds": 12})
        add_event(db, session, "progress", {"ratio": (i + 1) / 10})
    add_event(db, session, "incomplete_reason", {"reason": "not_interesting", "completion_ratio": 0.3})
    add_event(db, session, "enjoyment_feedback", {"enjoying": True, "prompted_at": "end"})

    events = db.query(S.TelemetryEvent).filter_by(session_id=session.id).all()
    assert S._feedback_score(events, 0.3) == 0.0


def test_early_exit_reason_penalizes_vs_clean_finish(db):
    _u1, bailed = _flashcards_session(db)
    _u2, finished = _flashcards_session(db)
    for i in range(4):
        for sess in (bailed, finished):
            add_event(db, sess, "dwell", {"seconds": 12})
            add_event(db, sess, "progress", {"ratio": (i + 1) / 10})
    add_event(db, bailed, "incomplete_reason", {"reason": "moving_on", "completion_ratio": 0.4})

    assert compute_engagement_score(db, bailed) < compute_engagement_score(db, finished)


def test_late_exit_reason_is_not_penalized(db):
    """Choosing a reason after basically finishing (>= cutoff) is just wrapping up."""
    _user, session = _flashcards_session(db)
    for i in range(10):
        add_event(db, session, "dwell", {"seconds": 12})
        add_event(db, session, "progress", {"ratio": (i + 1) / 10})
    add_event(db, session, "incomplete_reason", {"reason": "moving_on", "completion_ratio": 0.9})

    events = db.query(S.TelemetryEvent).filter_by(session_id=session.id).all()
    assert S._feedback_score(events, 1.0) == S.NEUTRAL_FEEDBACK_SCORE


def test_tab_switching_only_ever_reduces_score(db):
    _u1, focused = _flashcards_session(db)
    _u2, distracted = _flashcards_session(db)
    for i in range(10):
        for sess in (focused, distracted):
            add_event(db, sess, "dwell", {"seconds": 12})
            add_event(db, sess, "progress", {"ratio": (i + 1) / 10})
    for _ in range(3):
        add_event(db, distracted, "visibility_change", {"visible": False})

    assert compute_engagement_score(db, distracted) < compute_engagement_score(db, focused)


def test_summary_mode_still_scored_on_active_time(db):
    """Summary has no progress signal, so depth falls back to activity-gated dwell. An idle
    'completed' summary scores low; an attentively-read one scores high."""
    user = make_user(db)
    chat = make_chat(db, user)
    content = make_content(db, chat, mode="summary", content_json={"summary": "x" * 900})

    idle = make_session(db, user, content, status="completed", engagement_score=None)
    assert compute_engagement_score(db, idle) < 0.3

    read = make_session(db, user, content, status="completed", engagement_score=None)
    for _ in range(12):
        add_event(db, read, "dwell", {"seconds": 5})
        add_event(db, read, "scroll", {"scrollY": 100})
    assert compute_engagement_score(db, read) > 0.7
