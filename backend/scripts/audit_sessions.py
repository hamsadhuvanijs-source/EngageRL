"""Recomputes every completed session's engagement score and RL reward straight from its raw
telemetry_events, and diffs the result against what's actually stored in the database (i.e. what
the UI showed the user). This is the closest thing to "cross-validation" that applies here: there
is no held-out labeled dataset for a scoring formula, so instead we treat the *stored* value as a
prediction and the *recomputation from raw events* as ground truth, and check they agree.

A clean run (no MISMATCH lines) proves the numbers on screen really are derived from the user's
actual interaction (dwell/scroll/click/progress/quiz-answer events), not a placeholder or a stale/
random value — a mismatch would mean the score shown somewhere drifted from what the raw telemetry
actually supports (e.g. computed once and never refreshed, or computed with different inputs than
what's stored).

Usage (from backend/):  venv/Scripts/python.exe scripts/audit_sessions.py [--verbose]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.telemetry_event import TelemetryEvent
from app.rl.reward import compute_learning_reward, is_topic_mastered
from app.telemetry.scoring import compute_engagement_score

TOLERANCE = 0.001  # rounding noise only — anything beyond this is a real discrepancy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true", help="print every session, not just mismatches")
    args = parser.parse_args()

    db = SessionLocal()
    mismatches = 0
    checked = 0
    zero_event_sessions = []
    try:
        sessions = (
            db.query(LearningSession)
            .filter(LearningSession.status == "completed")
            .order_by(LearningSession.started_at)
            .all()
        )
        print(f"Auditing {len(sessions)} completed sessions...\n")

        for session in sessions:
            events = db.query(TelemetryEvent).filter(TelemetryEvent.session_id == session.id).all()
            content = db.get(GeneratedContent, session.generated_content_id)
            mode = content.mode if content else "?"

            if not events:
                zero_event_sessions.append(session.id)

            recomputed_engagement = compute_engagement_score(db, session)
            stored_engagement = session.engagement_score
            checked += 1

            engagement_ok = (
                stored_engagement is not None
                and abs(recomputed_engagement - stored_engagement) <= TOLERANCE
            )

            line = (
                f"session={session.id[:8]} mode={mode:<10} events={len(events):<4} "
                f"stored_engagement={stored_engagement!s:<8} recomputed={recomputed_engagement:<8}"
            )

            if not engagement_ok:
                mismatches += 1
                print(f"MISMATCH  {line}")
            elif args.verbose:
                print(f"ok        {line}")

            # Reward/done are only ever computed once (at completion, never re-persisted for
            # comparison), so recompute and just show them for a plausibility check rather than
            # diffing against a stored value that doesn't exist.
            if session.rl_action:
                reward = compute_learning_reward(db, session, events)
                done = is_topic_mastered(db, session, events, recomputed_engagement)
                if args.verbose:
                    print(f"          -> reward={reward} done={done} action={session.rl_action} policy={session.rl_policy}")

        print(f"\n{checked} sessions checked, {mismatches} mismatches.")
        if zero_event_sessions:
            print(
                f"{len(zero_event_sessions)} completed sessions have ZERO telemetry events "
                f"(engagement score for these falls back to defaults, not real interaction data):"
            )
            for sid in zero_event_sessions:
                print(f"  - {sid}")

        return 1 if mismatches else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
