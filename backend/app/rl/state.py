"""Learner state representation for the MDP — construction + discretization.

Tabular Q-learning needs a *finite, manageable* state space. Everything the app actually knows
about a learner is continuous or unbounded (a reading-pace multiplier, a rolling engagement
average, an open-ended mode history, ...), so this module's job is turning that into a small,
deterministic, discrete encoding: a `state_key` string that indexes the Q-table
(`app/models/q_state.py`), plus the readable `state_dict` behind it for logging/debugging.

State features (6 dimensions, cardinality noted) — each chosen from signals already computed
elsewhere in the app rather than inventing new ones:

  engagement      {low, medium, high}                         3   rolling avg of recent
                                                                    LearningSession.engagement_score
                                                                    (itself already a blend of dwell
                                                                    time, interaction rate, tab
                                                                    switching, completion and
                                                                    self-reported feedback — see
                                                                    telemetry/scoring.py — so this one
                                                                    bucket carries all of those
                                                                    signals without exploding the
                                                                    state space by giving each its own
                                                                    dimension)
  progress        {low, medium, high}                         3   rolling avg of recent raw
                                                                    completion/progress ratios
  pace            {fast, normal, slow}                         3   from User.reading_pace_multiplier
  quiz_accuracy   {low, medium, high, none}                    4   rolling accuracy over recent quiz
                                                                    sessions ("none" = no quiz history
                                                                    yet to judge)
  last_mode       {summary, quiz, flashcards, qa, flowchart,   9   most recent mode used *within this
                    podcast, comic, video, none}                   chat/topic* (the episode) — "none"
                                                                    if this is the first action of the
                                                                    episode
  content_length  {short, medium, long}                       3   reuses the existing (previously
                                                                    unused) app/rl/context.py bucket
                                                                    over this chat's source material

Worst-case cartesian product is 3*3*3*4*9*3 = 2916 — small enough that the Q-table stays
tractable, while in practice only a tiny, sparsely-visited fraction of it is ever reached by one
user's real session history (unvisited (state, action) pairs simply have no QState row — see
qlearning.py).

`STATE_HISTORY_WINDOW` recent *completed* sessions (across all of the user's chats, most recent
first) are used for the rolling features. Recency-windowed rather than all-time so the state
tracks how the learner is doing *lately*, not a fixed historical average that stops reacting to
change.
"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.chat import Chat
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.material_source import MaterialSource
from app.models.telemetry_event import TelemetryEvent
from app.models.user import User
from app.rl.context import length_bucket
from app.telemetry.scoring import quiz_accuracy as _quiz_accuracy_from_events
from app.telemetry.scoring import raw_progress_ratio

STATE_HISTORY_WINDOW = 5

# Bucket thresholds. Where a matching threshold already exists elsewhere in the app, it's reused
# here rather than invented fresh, so the state's notion of e.g. "good progress" agrees with
# what the UI already treats as "basically finished".
ENGAGEMENT_LOW_MAX = 0.4
ENGAGEMENT_HIGH_MIN = 0.7
PROGRESS_LOW_MAX = 0.5
PROGRESS_HIGH_MIN = 0.85  # matches frontend COMPLETION_WARN_THRESHOLD (app/sessions/[id]/page.tsx)
PACE_FAST_MAX = 1.05  # ~never confirmed a "still reading?" check-in
PACE_SLOW_MIN = 1.75  # confirmed it multiple times (PACE_BUMP_FACTOR=1.2, so ~3+ confirmations)
ACCURACY_LOW_MAX = 0.5
ACCURACY_HIGH_MIN = 0.8

NONE_LABEL = "none"


@dataclass(frozen=True)
class LearnerState:
    engagement: str
    progress: str
    pace: str
    quiz_accuracy: str
    last_mode: str
    content_length: str

    def as_dict(self) -> dict[str, str]:
        return {
            "engagement": self.engagement,
            "progress": self.progress,
            "pace": self.pace,
            "quiz_accuracy": self.quiz_accuracy,
            "last_mode": self.last_mode,
            "content_length": self.content_length,
        }

    @property
    def key(self) -> str:
        """Deterministic string encoding used as the Q-table's index. Sorted by feature name so
        the key never depends on dict/attribute iteration order."""
        return "|".join(f"{k}={v}" for k, v in sorted(self.as_dict().items()))


def parse_state_key(state_key: str) -> dict[str, str]:
    """Inverse of LearnerState.key — QState rows only persist the compact key (it's the index),
    so debug/inspection endpoints that need the readable feature breakdown back (e.g. the
    Q-table view in app/rl/router.py) reconstruct it from the key rather than storing the same
    information twice."""
    result: dict[str, str] = {}
    for part in state_key.split("|"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        result[k] = v
    return result


def _bucket3(value: float, low_max: float, high_min: float, labels: tuple[str, str, str]) -> str:
    if value <= low_max:
        return labels[0]
    if value >= high_min:
        return labels[2]
    return labels[1]


def recent_completed_sessions(db: Session, user_id: str, limit: int = STATE_HISTORY_WINDOW) -> list[LearningSession]:
    return (
        db.query(LearningSession)
        .filter(LearningSession.user_id == user_id, LearningSession.status == "completed")
        .order_by(LearningSession.completed_at.desc())
        .limit(limit)
        .all()
    )


def _events_by_session(db: Session, session_ids: list[str]) -> dict[str, list[TelemetryEvent]]:
    if not session_ids:
        return {}
    events = db.query(TelemetryEvent).filter(TelemetryEvent.session_id.in_(session_ids)).all()
    by_session: dict[str, list[TelemetryEvent]] = {sid: [] for sid in session_ids}
    for e in events:
        by_session.setdefault(e.session_id, []).append(e)
    return by_session


def _engagement_level(recent_sessions: list[LearningSession]) -> str:
    scored = [s.engagement_score for s in recent_sessions if s.engagement_score is not None]
    if not scored:
        return "medium"  # neutral prior for a learner with no scored history yet
    avg = sum(scored) / len(scored)
    return _bucket3(avg, ENGAGEMENT_LOW_MAX, ENGAGEMENT_HIGH_MIN, ("low", "medium", "high"))


def _progress_level(recent_sessions: list[LearningSession], events_by_session: dict[str, list[TelemetryEvent]]) -> str:
    ratios = [
        r
        for s in recent_sessions
        if (r := raw_progress_ratio(events_by_session.get(s.id, []))) is not None
    ]
    if not ratios:
        return "medium"
    avg = sum(ratios) / len(ratios)
    return _bucket3(avg, PROGRESS_LOW_MAX, PROGRESS_HIGH_MIN, ("low", "medium", "high"))


def _pace_level(user: User | None) -> str:
    multiplier = user.reading_pace_multiplier if user else 1.0
    if multiplier <= PACE_FAST_MAX:
        return "fast"
    if multiplier >= PACE_SLOW_MIN:
        return "slow"
    return "normal"


def _quiz_accuracy_level(
    db: Session, recent_sessions: list[LearningSession], events_by_session: dict[str, list[TelemetryEvent]]
) -> str:
    # QA mode is free-form question/answer with no single correct option, so it has nothing to
    # score — only "quiz" mode sessions carry an accuracy signal.
    quiz_content_ids = {
        s.generated_content_id
        for s in recent_sessions
        if s.rl_action == "quiz"
        or (s.rl_action is None and _mode_for_content(db, s.generated_content_id) == "quiz")
    }
    accuracies = [
        acc
        for s in recent_sessions
        if s.generated_content_id in quiz_content_ids
        and (acc := _quiz_accuracy_from_events(events_by_session.get(s.id, []))) is not None
    ]
    if not accuracies:
        return NONE_LABEL
    avg = sum(accuracies) / len(accuracies)
    return _bucket3(avg, ACCURACY_LOW_MAX, ACCURACY_HIGH_MIN, ("low", "medium", "high"))


def _mode_for_content(db: Session, content_id: str) -> str | None:
    content = db.get(GeneratedContent, content_id)
    return content.mode if content else None


def _last_mode_in_topic(db: Session, user_id: str, chat_id: str) -> str:
    """Most recent completed session's mode *within this chat* — the episode-local "recent
    format history" signal, so the policy can see what was just tried on this exact topic
    before choosing the next action for it."""
    last = (
        db.query(LearningSession)
        .join(GeneratedContent, LearningSession.generated_content_id == GeneratedContent.id)
        .filter(
            LearningSession.user_id == user_id,
            GeneratedContent.chat_id == chat_id,
            LearningSession.status == "completed",
        )
        .order_by(LearningSession.completed_at.desc())
        .first()
    )
    if last is None:
        return NONE_LABEL
    return _mode_for_content(db, last.generated_content_id) or NONE_LABEL


def _content_length_bucket(db: Session, chat: Chat) -> str:
    sources = db.query(MaterialSource).filter(MaterialSource.chat_id == chat.id).all()
    total_chars = sum(s.char_count for s in sources)
    return length_bucket(total_chars)


def compute_state(db: Session, user: User, chat: Chat) -> LearnerState:
    """Builds the discretized learner state used both to select the next action (app/rl/policy.py)
    and, after the learner interacts with that action's content, to describe where they ended up
    (the `next_state` half of the recorded transition). Same function either way — the state
    just reflects whatever history exists in the database at the moment it's called."""
    recent_sessions = recent_completed_sessions(db, user.id)
    events_by_session = _events_by_session(db, [s.id for s in recent_sessions])

    return LearnerState(
        engagement=_engagement_level(recent_sessions),
        progress=_progress_level(recent_sessions, events_by_session),
        pace=_pace_level(user),
        quiz_accuracy=_quiz_accuracy_level(db, recent_sessions, events_by_session),
        last_mode=_last_mode_in_topic(db, user.id, chat.id),
        content_length=_content_length_bucket(db, chat),
    )
