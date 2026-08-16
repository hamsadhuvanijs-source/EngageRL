import json
import math

from sqlalchemy.orm import Session

from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User

READING_CHARS_PER_SECOND = 15.0
CHARS_PER_EXPECTED_INTERACTION = 200.0
MIN_EXPECTED_INTERACTIONS = 5.0
MIN_EXPECTED_SECONDS = 5.0

# Interactive modes involve thinking/recalling, not just reading, so a flat chars-per-second
# rate badly underestimates them regardless of how much text the JSON happens to contain — a
# "hard" quiz question needs real time to reason through even if it's phrased in five words.
# These are per-item time budgets, scaled by the user's chosen difficulty/answer-style options
# (already stored on the content) and the actual item count, not text length.
QUIZ_SECONDS_PER_QUESTION = {"easy": 20.0, "medium": 35.0, "hard": 55.0}
FLASHCARD_SECONDS_PER_CARD = {"easy": 8.0, "medium": 12.0, "hard": 18.0}
QA_SECONDS_PER_ITEM = {"short": 15.0, "long": 35.0}
DEFAULT_DIFFICULTY = "medium"
DEFAULT_ANSWER_STYLE = "long"

# Extra time to actually look at each comic panel's artwork, on top of reading its dialogue.
COMIC_SECONDS_PER_PANEL = 8.0

# Dwelling longer than expected isn't automatically good. Up to this multiple of the expected
# reading time is treated as normal (careful readers, re-reading a tricky part) and still gets
# full credit. Past that, credit only holds if interactions kept pace too — otherwise the extra
# time reads as an idle/abandoned tab, not engagement, and decays back down instead of capping
# at max the way a naive ratio-clamp would. The same threshold is used client-side as the trigger
# for the "still with it?" check-in popup, so the UI nudge and the scoring cliff line up.
DWELL_OVERAGE_TOLERANCE = 2.0
DWELL_DECAY_RATE = 0.5
IDLE_DENSITY_THRESHOLD = 0.5

# When a user confirms a check-in wasn't disinterest (just a slower pace), their personal
# expected-time baseline grows by this factor for every future session, capped so it can't
# drift unboundedly if they keep confirming.
PACE_BUMP_FACTOR = 1.2
MAX_PACE_MULTIPLIER = 3.0

WEIGHT_DWELL = 0.30
WEIGHT_INTERACTION = 0.20
WEIGHT_TAB_PENALTY = 0.15
WEIGHT_COMPLETION = 0.15
WEIGHT_FEEDBACK = 0.20

INTERACTION_EVENT_TYPES = {"scroll", "keypress", "mouse_move", "click"}

# Neutral prior used when a session carries no explicit "did you enjoy this" signal at all
# (older sessions, or ones the user never responded to) — keeps feedback from silently
# dragging the score up or down for sessions where we simply don't have the data.
NEUTRAL_FEEDBACK_SCORE = 0.5


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _dwell_ratio(
    active_dwell_seconds: float,
    expected_seconds: float,
    overage_threshold_seconds: float,
    interaction_events: int,
    expected_interactions: float,
) -> float:
    if active_dwell_seconds <= overage_threshold_seconds:
        return _clamp(active_dwell_seconds / expected_seconds)

    # Way past a normal read for this much content — only still "engaged" if interactions kept
    # a proportional pace throughout, not just at the start before the user wandered off.
    interaction_density = interaction_events / max(active_dwell_seconds, 1.0)
    expected_density = expected_interactions / expected_seconds
    if interaction_density >= expected_density * IDLE_DENSITY_THRESHOLD:
        return 1.0

    # Normalize the overage by expected_seconds so the decay curve's steepness stays consistent
    # across short and long content.
    overage = (active_dwell_seconds - overage_threshold_seconds) / expected_seconds
    return _clamp(math.exp(-DWELL_DECAY_RATE * overage))


def _completion_ratio(events: list[TelemetryEvent], status: str) -> float:
    """How much of the actual content the user got through, from real per-mode progress
    telemetry (answered questions / total, cards seen / total, video seconds watched / total,
    etc — pushed by each mode's view component as the user progresses). Progress is monotonic —
    the max ratio ever reported wins, so scrolling/navigating back doesn't erase credit already
    earned.

    Content-item progress isn't tracked for every mode (e.g. summary has no discrete items), so
    when there's no progress signal at all we fall back to the pre-existing status-only estimate
    rather than assuming 0% and tanking the score for modes that were never instrumented."""
    ratios = [
        float((e.payload or {}).get("ratio", 0))
        for e in events
        if e.event_type == "progress" and (e.payload or {}).get("ratio") is not None
    ]
    if not ratios:
        return 1.0 if status == "completed" else 0.5

    ratio = _clamp(max(ratios))
    return ratio * (1.0 if status == "completed" else 0.5)


def _feedback_score(events: list[TelemetryEvent]) -> float:
    """Real self-reported engagement, not inferred — "are you enjoying this?" mid-session/
    end-session check-ins, plus an implicit negative if the user's stated reason for marking a
    session complete early was "not interesting". Takes the most recent signal chronologically
    (a later answer supersedes an earlier one), and stays neutral if the user never answered."""
    signals: list[tuple[object, bool]] = []
    for e in events:
        payload = e.payload or {}
        if e.event_type == "enjoyment_feedback" and "enjoying" in payload:
            signals.append((e.client_ts, bool(payload["enjoying"])))
        elif e.event_type == "incomplete_reason" and payload.get("reason") == "not_interesting":
            signals.append((e.client_ts, False))

    if not signals:
        return NEUTRAL_FEEDBACK_SCORE

    signals.sort(key=lambda s: s[0])
    return 1.0 if signals[-1][1] else 0.0


def _content_char_count(content: GeneratedContent | None) -> int:
    """How much text the user was actually shown — NOT the raw source material,
    which can be many times longer than the generated summary/quiz/etc. Using the
    source length here made `expected_seconds` wildly oversized (e.g. ~9 minutes
    for a 10-second quiz), which pinned dwell/interaction ratios near zero."""
    if not content or not content.content_json:
        return 0
    return len(json.dumps(content.content_json))


def _reading_seconds(content: GeneratedContent | None) -> float:
    return max(_content_char_count(content) / READING_CHARS_PER_SECOND, MIN_EXPECTED_SECONDS)


def _base_expected_seconds(content: GeneratedContent | None) -> float:
    """How long this specific piece of content should reasonably take, mode-aware — NOT a flat
    reading-speed estimate for every mode. Video uses the actual sum of each scene's playback
    duration (real data already sitting in content_json); quiz/flashcards/qa use a per-item time
    budget scaled by the user's chosen difficulty/count/answer-style; comic adds a per-panel
    viewing allowance on top of dialogue reading time. Anything else (summary, and any
    unrecognized/malformed shape) falls back to pure reading time over the shown text."""
    if not content or not content.content_json:
        return MIN_EXPECTED_SECONDS

    cj = content.content_json
    options = content.options_json or {}

    if content.mode == "video":
        total = sum(float(scene.get("duration", 0)) for scene in (cj.get("scenes") or []))
        if total > 0:
            return max(total, MIN_EXPECTED_SECONDS)

    elif content.mode == "quiz":
        count = len(cj.get("quiz") or [])
        if count > 0:
            difficulty = options.get("difficulty") if options.get("difficulty") in QUIZ_SECONDS_PER_QUESTION else DEFAULT_DIFFICULTY
            return max(count * QUIZ_SECONDS_PER_QUESTION[difficulty], MIN_EXPECTED_SECONDS)

    elif content.mode == "flashcards":
        count = len(cj.get("cards") or [])
        if count > 0:
            difficulty = options.get("difficulty") if options.get("difficulty") in FLASHCARD_SECONDS_PER_CARD else DEFAULT_DIFFICULTY
            return max(count * FLASHCARD_SECONDS_PER_CARD[difficulty], MIN_EXPECTED_SECONDS)

    elif content.mode == "qa":
        count = len(cj.get("items") or [])
        if count > 0:
            answer_style = options.get("answer_style") if options.get("answer_style") in QA_SECONDS_PER_ITEM else DEFAULT_ANSWER_STYLE
            return max(count * QA_SECONDS_PER_ITEM[answer_style], MIN_EXPECTED_SECONDS)

    elif content.mode == "comic":
        panel_count = len(cj.get("panels") or [])
        return max(_reading_seconds(content) + panel_count * COMIC_SECONDS_PER_PANEL, MIN_EXPECTED_SECONDS)

    return _reading_seconds(content)


def expected_seconds_for_session(db: Session, session: LearningSession) -> tuple[float, float]:
    """Returns (expected_seconds, overage_threshold_seconds) for this session's content,
    personalized to the user's reading_pace_multiplier. Shared by the final engagement-score
    calculation and by the live session endpoint that tells the frontend when to show the
    "still with it?" check-in, so both use the exact same numbers."""
    content = db.get(GeneratedContent, session.generated_content_id)
    user = db.get(User, session.user_id)
    pace_multiplier = user.reading_pace_multiplier if user else 1.0

    expected_seconds = _base_expected_seconds(content) * pace_multiplier
    overage_threshold_seconds = expected_seconds * DWELL_OVERAGE_TOLERANCE
    return expected_seconds, overage_threshold_seconds


def bump_reading_pace(user: User) -> float:
    """Called when the user confirms they're still engaged despite tripping the overage
    check-in — grows their personal pace multiplier so future sessions get a longer grace
    window before flagging them again."""
    user.reading_pace_multiplier = min(user.reading_pace_multiplier * PACE_BUMP_FACTOR, MAX_PACE_MULTIPLIER)
    return user.reading_pace_multiplier


def compute_engagement_score(db: Session, session: LearningSession) -> float:
    content = db.get(GeneratedContent, session.generated_content_id)
    char_count = _content_char_count(content)
    expected_seconds, overage_threshold_seconds = expected_seconds_for_session(db, session)

    events = db.query(TelemetryEvent).filter(TelemetryEvent.session_id == session.id).all()

    tab_switch_count = sum(
        1 for e in events if e.event_type == "visibility_change" and (e.payload or {}).get("visible") is False
    )
    active_dwell_seconds = sum(float((e.payload or {}).get("seconds", 0)) for e in events if e.event_type == "dwell")
    interaction_events = sum(1 for e in events if e.event_type in INTERACTION_EVENT_TYPES)

    expected_interactions = max(char_count / CHARS_PER_EXPECTED_INTERACTION, MIN_EXPECTED_INTERACTIONS)

    tab_penalty = _clamp(1 - 0.1 * tab_switch_count)
    dwell_ratio = _dwell_ratio(
        active_dwell_seconds, expected_seconds, overage_threshold_seconds, interaction_events, expected_interactions
    )
    interaction_rate = _clamp(interaction_events / expected_interactions)
    completion_bonus = _completion_ratio(events, session.status)
    feedback_score = _feedback_score(events)

    score = (
        WEIGHT_DWELL * dwell_ratio
        + WEIGHT_INTERACTION * interaction_rate
        + WEIGHT_TAB_PENALTY * tab_penalty
        + WEIGHT_COMPLETION * completion_bonus
        + WEIGHT_FEEDBACK * feedback_score
    )
    return round(_clamp(score), 4)
