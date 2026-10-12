"""Reward and episode-termination logic for the Q-learning MDP.

The reward is deliberately built *on top of* the existing engagement score
(`telemetry.scoring.compute_engagement_score`) rather than replacing it. That score is built to
resist the obvious gaming routes: dwell only accrues while the learner is actually active
(idle-filtered client-side) and is capped once it matches the expected pace; the largest term is
*depth* — how much of the content was genuinely engaged with (answers given, cards flipped,
media played), not how many clicks were logged; and tab-switching only ever subtracts. Two more
terms are layered on here to make it a genuine *learning* reward rather than a pure engagement
reward:

  - a quiz-accuracy component, where available, so a session that felt engaging but was
    answered mostly wrong doesn't score as well as one with real comprehension
  - an improvement component, comparing this session's engagement against the learner's own
    recent rolling average — rewarding getting better, not just being at some absolute level,
    which matters for a learner who started low
"""

from sqlalchemy.orm import Session

from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.telemetry_event import TelemetryEvent
from app.rl.state import STATE_HISTORY_WINDOW, recent_completed_sessions
from app.telemetry.scoring import compute_engagement_score, quiz_accuracy, resolve_progress

WEIGHT_BASE_ENGAGEMENT = 0.7
WEIGHT_QUIZ_ACCURACY = 0.2
WEIGHT_IMPROVEMENT = 0.1

# Used when a component doesn't apply to this session (e.g. no quiz answers) — redistributes
# that weight back onto the base engagement score rather than silently dragging the reward
# toward zero for modes that were never meant to carry that signal.
NEUTRAL_COMPONENT = 0.5

# "Topic mastered" heuristic — see is_topic_mastered() below.
MASTERY_PROGRESS_THRESHOLD = 0.9
MASTERY_ACCURACY_THRESHOLD = 0.7
MASTERY_ENGAGEMENT_THRESHOLD = 0.7


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _recent_engagement_baseline(db: Session, user_id: str, exclude_session_id: str) -> float | None:
    """Rolling average engagement over the learner's recent history, same window as the state
    representation, excluding the session currently being scored — this is the "recent past"
    the improvement component compares against."""
    recent = [
        s
        for s in recent_completed_sessions(db, user_id, limit=STATE_HISTORY_WINDOW + 1)
        if s.id != exclude_session_id and s.engagement_score is not None
    ]
    if not recent:
        return None
    return sum(s.engagement_score for s in recent) / len(recent)


def compute_learning_reward(db: Session, session: LearningSession, events: list[TelemetryEvent]) -> float:
    """The Q-learning reward for the transition this session represents. `events` is passed in
    (rather than re-queried) because the caller already has it from computing the engagement
    score and the next state."""
    base_engagement = compute_engagement_score(db, session)

    accuracy = quiz_accuracy(events)
    accuracy_component = accuracy if accuracy is not None else NEUTRAL_COMPONENT

    baseline = _recent_engagement_baseline(db, session.user_id, exclude_session_id=session.id)
    if baseline is None:
        improvement_component = NEUTRAL_COMPONENT
    else:
        # Rescale the [-1, 1] delta against the learner's own baseline into [0, 1], so "exactly
        # as good as usual" sits at the same neutral 0.5 as the other components.
        improvement_component = _clamp01(0.5 + (base_engagement - baseline) / 2)

    reward = (
        WEIGHT_BASE_ENGAGEMENT * base_engagement
        + WEIGHT_QUIZ_ACCURACY * accuracy_component
        + WEIGHT_IMPROVEMENT * improvement_component
    )
    return round(_clamp01(reward), 4)


def is_topic_mastered(
    db: Session, session: LearningSession, events: list[TelemetryEvent], engagement_score: float
) -> bool:
    """Episode-termination heuristic: does this completed session look like the learner actually
    got through and understood this action's content, rather than just marking it done?

    This is the "initial design" the episode boundary calls for — a learning topic (one Chat) is
    the episode, and a session ends it when the learner shows strong, real signal on it (high
    progress, strong quiz accuracy where applicable, solid engagement). It's a heuristic proxy,
    not a ground-truth "the user is done with this topic" signal — there's no such explicit
    action in the product yet. Sessions that don't clear this bar are non-terminal: the episode
    for that chat is treated as still open, and the Q-update bootstraps off the next state's
    best action value instead of the reward alone."""
    if session.status != "completed":
        return False
    if engagement_score < MASTERY_ENGAGEMENT_THRESHOLD:
        return False

    content = db.get(GeneratedContent, session.generated_content_id)
    progress = resolve_progress(events, content.mode if content else None)
    if progress is not None and progress < MASTERY_PROGRESS_THRESHOLD:
        return False

    if content and content.mode == "quiz":
        accuracy = quiz_accuracy(events)
        if accuracy is not None and accuracy < MASTERY_ACCURACY_THRESHOLD:
            return False

    return True
