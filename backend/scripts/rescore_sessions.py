"""Recompute stored engagement scores (and, optionally, the whole RL history) after a change to
the scoring model in app/telemetry/scoring.py.

Why this exists: `session.engagement_score` is written once at completion and then read forever
by the stats dashboard, the RL learner-state features, and the RL reward. When the scoring
formula changes, every historical score is stale — and the Q-table / bandit posteriors were
trained on the old (in this case, inflated) numbers. This script brings them back in sync.

Usage (from backend/):
    venv/Scripts/python.exe scripts/rescore_sessions.py                # dry run — show diffs only
    venv/Scripts/python.exe scripts/rescore_sessions.py --apply        # rewrite engagement_score
    venv/Scripts/python.exe scripts/rescore_sessions.py --apply --replay-rl
        # ALSO wipe bandit_state / q_state / rl_transition per user and replay every completed
        # session through the RL update in completed_at order.

Caveat on --replay-rl: the bandit posteriors (the "learning style preference" bars, and the
cold-start policy) are replayed exactly — they only depend on (action, reward). The Q-table's
bootstrap target (next_state) is computed against the current DB, so during replay it can "see"
sessions that were actually still in the future; Q-values end up slightly off but keep
converging from every new, correctly-scored session. Historical flashcards/Q&A sessions also
still carry their old navigation-based `progress` events, so their recomputed score is closer to
honest but not identical to what the fixed frontend would now record.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models.bandit_state import BanditState
from app.models.generated_content import GeneratedContent
from app.models.learning_session import LearningSession
from app.models.q_state import QState
from app.models.rl_transition import RLTransition
from app.models.telemetry_event import TelemetryEvent
from app.rl.policy import record_outcome
from app.telemetry.scoring import compute_engagement_score


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write the recomputed engagement scores")
    parser.add_argument(
        "--replay-rl",
        action="store_true",
        help="also reset and replay bandit_state / q_state / rl_transition (implies --apply)",
    )
    args = parser.parse_args()
    apply = args.apply or args.replay_rl

    db = SessionLocal()
    try:
        sessions = (
            db.query(LearningSession)
            .filter(LearningSession.status == "completed")
            .order_by(LearningSession.completed_at)
            .all()
        )
        print(f"{len(sessions)} completed sessions\n")

        moved_down = moved_up = 0
        total_delta = 0.0
        for s in sessions:
            content = db.get(GeneratedContent, s.generated_content_id)
            mode = content.mode if content else "?"
            old = s.engagement_score
            new = compute_engagement_score(db, s)
            if old is not None:
                delta = new - old
                total_delta += delta
                moved_down += delta < -0.02
                moved_up += delta > 0.02
                flag = "  " if abs(delta) <= 0.05 else ("vv" if delta < 0 else "^^")
                print(f"{flag} {s.id[:8]} {mode:<10} {str(old):<8} -> {new:<8} ({delta:+.3f})")
            if apply:
                s.engagement_score = new

        n = sum(1 for s in sessions if s.engagement_score is not None)
        print(
            f"\navg change: {total_delta / n:+.3f} over {n} scored sessions "
            f"({moved_down} dropped, {moved_up} rose)"
        )

        if apply:
            db.commit()
            print("engagement_score rewritten.")

        if args.replay_rl:
            user_ids = {s.user_id for s in sessions}
            for uid in user_ids:
                db.query(RLTransition).filter_by(user_id=uid).delete(synchronize_session=False)
                db.query(QState).filter_by(user_id=uid).delete(synchronize_session=False)
                db.query(BanditState).filter_by(user_id=uid).delete(synchronize_session=False)
            db.commit()
            print(f"\nreset RL state for {len(user_ids)} user(s); replaying {len(sessions)} sessions...")
            for s in sessions:
                record_outcome(db, s)
            print("RL replay complete.")

        if not apply:
            print("\n(dry run — nothing written. re-run with --apply or --apply --replay-rl)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
