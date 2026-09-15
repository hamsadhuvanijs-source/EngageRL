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

# A flowchart/mindmap is studied node by node, not read straight through — text length badly
# underestimates it (a 6-word node can encode a whole concept worth pausing on). Budget time per
# line of Mermaid syntax, each line being roughly one node or one edge. The mode reports no
# discrete progress (like summary), so this expected-time estimate is the main lever the dwell
# component has for scoring a flowchart session.
FLOWCHART_SECONDS_PER_NODE = 11.0

# Podcast is listened to, not read — the flat reading_seconds chars/sec fallback assumes silent
# reading speed, which runs faster than natural speech. ~150 wpm matches the Web Speech API's
# default rate (see frontend PodcastView), so expected time tracks what's actually being played.
PODCAST_WORDS_PER_SECOND = 2.5

# Dwelling longer than expected isn't automatically good. Up to this multiple of the expected
# reading time is treated as normal (careful readers, re-reading a tricky part) and still gets
# full credit. Past that, credit only holds if interactions kept pace too — otherwise the extra
# time reads as an idle/abandoned tab, not engagement, and decays back down instead of capping
# at max the way a naive ratio-clamp would. The same threshold is used client-side as the trigger
# for the "still with it?" check-in popup, so the UI nudge and the scoring cliff line up.
#
# Note the *lower* end is handled client-side now: the frontend only credits "dwell" seconds
# while the learner is actually doing something (scroll / key / click / mode progress within the
# last IDLE_GRACE_MS — see TelemetryProvider). Time with the tab open but the learner idle
# never reaches this module, so "run out the expected clock by leaving it open" no longer scores.
DWELL_OVERAGE_TOLERANCE = 2.0
DWELL_DECAY_RATE = 0.5
IDLE_DENSITY_THRESHOLD = 0.5

# When a user confirms a check-in wasn't disinterest (just a slower pace), their personal
# expected-time baseline grows by this factor for every future session, capped so it can't
# drift unboundedly if they keep confirming.
PACE_BUMP_FACTOR = 1.2
MAX_PACE_MULTIPLIER = 3.0

# Weights sum to 1.0. There is deliberately no standalone "tab penalty" term any more — it used
# to be a one-sided penalty that still handed out its full weight (0.15) to anyone who simply
# didn't switch tabs, putting a hard floor under otherwise-disengaged sessions. Tab-switching is
# now a multiplicative penalty on the final score (TAB_SWITCH_* below) so it can only ever pull a
# score down. Likewise there's no standalone "interaction rate" term — counting raw scroll/click/
# mouse events against a low bar was trivially maxed by clicking through content without reading
# it. What matters is *depth*: how much of the content the learner actually engaged with.
WEIGHT_DWELL = 0.30       # active (client-side idle-filtered) time vs the expected pace
WEIGHT_DEPTH = 0.35       # fraction of the content the learner genuinely got into
WEIGHT_COMPLETION = 0.15  # progress reached, discounted if never marked complete
WEIGHT_FEEDBACK = 0.20    # self-reported enjoyment + reason for any early exit

TAB_SWITCH_PENALTY_PER_SWITCH = 0.07
TAB_SWITCH_PENALTY_FLOOR = 0.55

# Tapping "I'm done" before this fraction of the content is a real disengagement signal, scored
# by the stated reason. At/after it, wrapping up is just finishing and carries no penalty. The
# cutoff matches the frontend's COMPLETION_WARN_THRESHOLD (app/sessions/[id]/page.tsx).
EARLY_EXIT_PROGRESS_CUTOFF = 0.85
EARLY_EXIT_REASON_SCORES = {
    "not_interesting": 0.0,
    "too_hard": 0.15,
    "moving_on": 0.35,
    "ran_out_of_time": 0.5,  # an external constraint, not a verdict on the format
}

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


def raw_progress_ratio(events: list[TelemetryEvent]) -> float | None:
    """How far through the actual content the user got (0-1), from real per-mode progress
    telemetry (answered questions / total, cards seen / total, video seconds watched / total,
    etc — pushed by each mode's view component as the user progresses). Progress is monotonic —
    the max ratio ever reported wins, so scrolling/navigating back doesn't erase credit already
    earned. Returns None (not 0.0) when the mode has no discrete-item tracking (e.g. summary) or
    the events just aren't there — "we don't know" is a different thing from "0% done", and
    callers (engagement scoring, RL state/reward) need to be able to tell them apart instead of
    both collapsing to a phantom zero.

    Exported (not prefixed `_`) because app/rl/state.py and app/rl/reward.py both need this same
    raw signal — the MDP's progress-based state feature and terminal/mastery check must reason
    about actual completion, not the status-blended score below."""
    ratios = [
        float((e.payload or {}).get("ratio", 0))
        for e in events
        if e.event_type == "progress" and (e.payload or {}).get("ratio") is not None
    ]
    return _clamp(max(ratios)) if ratios else None


# Modes whose view reports progress on *any* genuine engagement (an answer, a card flip, an
# item revealed, a panel scrolled into view). For these, a session with NO progress telemetry
# means the learner really did get 0% into the content — not "we can't tell" — so it scores as
# 0, no time/status fallback.
#
# Deliberately excluded: summary and flowchart (one block, nothing discrete to track); and
# podcast/video, whose progress only fires during media playback — a learner who reads the
# transcript instead produces none, so those keep the `None` -> fall-back-to-active-dwell path.
PROGRESS_TRACKED_MODES = {"quiz", "flashcards", "qa", "comic"}


def resolve_progress(events: list[TelemetryEvent], mode: str | None) -> float | None:
    """`raw_progress_ratio`, but a progress-tracked mode (see PROGRESS_TRACKED_MODES) that
    reported nothing resolves to 0.0 rather than None — for those modes "no progress events"
    is real data, not missing data."""
    ratio = raw_progress_ratio(events)
    if ratio is None and mode in PROGRESS_TRACKED_MODES:
        return 0.0
    return ratio


def quiz_accuracy(events: list[TelemetryEvent]) -> float | None:
    """Fraction of quiz questions answered correctly, from real per-answer "quiz_answer"
    telemetry (pushed by QuizView as each question is answered) — not a proxy, the actual
    correct/incorrect outcome the user saw. None if this session has no quiz answers to judge
    (wrong mode, or no answers yet)."""
    outcomes = [
        bool((e.payload or {}).get("correct"))
        for e in events
        if e.event_type == "quiz_answer" and "correct" in (e.payload or {})
    ]
    return sum(outcomes) / len(outcomes) if outcomes else None


def _completion_ratio(progress: float | None, status: str) -> float:
    """The completion signal as used by the engagement score: the resolved progress ratio scaled
    down for sessions that were never marked complete, or a status-only estimate when the mode
    has no progress signal at all (summary, flowchart) — 1.0 if the user still finished, 0.5
    otherwise."""
    if progress is None:
        return 1.0 if status == "completed" else 0.5
    return progress * (1.0 if status == "completed" else 0.5)


def _feedback_score(events: list[TelemetryEvent], progress: float | None) -> float:
    """Combines every self-report signal in the session into one [0, 1] value:
      - explicit "are you enjoying this?" answers (1.0 = yes, 0.0 = no)
      - the reason given for ending a session early, when it was ended before
        EARLY_EXIT_PROGRESS_CUTOFF of the content (see EARLY_EXIT_REASON_SCORES)

    Multiple signals are combined with min(), NOT "most recent wins". The completion flow shows
    the enjoyment prompt *after* the early-exit-reason prompt, so "most recent" let a reflexive
    end-of-session 🙂 silently overwrite a genuine "this isn't working for me, I'm leaving at
    40%". Neutral (0.5) only when there is no signal at all."""
    reached = progress if progress is not None else 1.0
    scores: list[float] = []
    for e in events:
        payload = e.payload or {}
        if e.event_type == "enjoyment_feedback" and "enjoying" in payload:
            scores.append(1.0 if payload["enjoying"] else 0.0)
        elif e.event_type == "incomplete_reason":
            client_ratio = float(payload.get("completion_ratio", 0.0) or 0.0)
            reason = payload.get("reason")
            if max(reached, client_ratio) < EARLY_EXIT_PROGRESS_CUTOFF and reason in EARLY_EXIT_REASON_SCORES:
                scores.append(EARLY_EXIT_REASON_SCORES[reason])

    return min(scores) if scores else NEUTRAL_FEEDBACK_SCORE


def _content_depth(progress: float | None, dwell_ratio: float) -> float:
    """How much of the content the learner actually got into — the term that separates "read
    it" from "clicked through it". Uses real per-mode progress (quiz questions answered,
    flashcards *flipped*, Q&A items *revealed*, video/podcast seconds played, comic panels
    scrolled past). Only when a mode has no discrete progress signal at all (summary, flowchart)
    does it fall back to the activity-gated dwell ratio — the only "engaged with a single block
    of prose/diagram" proxy available."""
    return progress if progress is not None else dwell_ratio


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

    elif content.mode == "flowchart":
        mermaid = cj.get("mermaid") if isinstance(cj.get("mermaid"), str) else ""
        # Drop the header line ("flowchart TD" / "mindmap"); the rest are ~one node/edge each.
        node_lines = [ln for ln in mermaid.splitlines()[1:] if ln.strip()]
        if node_lines:
            return max(len(node_lines) * FLOWCHART_SECONDS_PER_NODE, MIN_EXPECTED_SECONDS)

    elif content.mode == "podcast":
        word_count = sum(len((seg.get("text") or "").split()) for seg in (cj.get("segments") or []))
        if word_count > 0:
            return max(word_count / PODCAST_WORDS_PER_SECOND, MIN_EXPECTED_SECONDS)

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

    progress = resolve_progress(events, content.mode if content else None)
    dwell_ratio = _dwell_ratio(
        active_dwell_seconds, expected_seconds, overage_threshold_seconds, interaction_events, expected_interactions
    )
    depth = _content_depth(progress, dwell_ratio)
    completion_bonus = _completion_ratio(progress, session.status)
    feedback_score = _feedback_score(events, progress)

    score = (
        WEIGHT_DWELL * dwell_ratio
        + WEIGHT_DEPTH * depth
        + WEIGHT_COMPLETION * completion_bonus
        + WEIGHT_FEEDBACK * feedback_score
    )
    # Tab-switching away mid-session can only ever reduce the score — never a free component.
    tab_multiplier = max(TAB_SWITCH_PENALTY_FLOOR, 1.0 - TAB_SWITCH_PENALTY_PER_SWITCH * tab_switch_count)
    return round(_clamp(score * tab_multiplier), 4)
