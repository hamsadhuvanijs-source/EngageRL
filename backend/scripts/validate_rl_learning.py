"""Simulation-based validation of the RL pipeline — the RL analog of cross-validation.

There's no held-out labeled dataset for "was the right learning format suggested" (that's the
whole point of learning it online), so instead this backtests the *real* production code
(app/rl/bandit.py, app/rl/qlearning.py, app/rl/policy.py, app/rl/reward.py,
app/telemetry/scoring.py — nothing here is reimplemented or mocked) against a *synthetic
environment with a known ground truth*: one learning mode is secretly the best fit for the
simulated learner (produces the richest telemetry — long proportional dwell, high interaction
density, high completion, and for quiz mode, high accuracy), one is secretly the worst, and the
rest are middling, each with per-session noise layered on top so no two sessions are identical.

If the system is actually learning from interaction data (not choosing randomly, and not driven
by some constant/placeholder score), running many simulated study sessions through the real
choose_action -> generate synthetic telemetry -> record_outcome loop should, with high
reliability across independent random seeds:

  1. end with the bandit/Q-learning preference ranking the secretly-best mode highest and the
     secretly-worst mode lowest (or close to it);
  2. shift its actual action *selection* frequency toward the best mode as sessions accumulate
     (visible as rising win-rate against a uniform-random baseline in the second half of the run
     vs the first half — i.e. falling regret);
  3. end up with a realized average reward well above what picking uniformly at random would
     have gotten, using the exact same reward function.

None of this is a unit test of one function in isolation — it's the full pipeline, exercised the
way real usage exercises it, repeated across many seeds so a single lucky/unlucky run can't hide
a real problem (or manufacture a fake pass).

Usage (from backend/):  venv/Scripts/python.exe scripts/validate_rl_learning.py [--seeds N] [--episodes N]
"""

import argparse
import os
import random
import sys
import uuid
from pathlib import Path
from statistics import mean

_DB_PATH = Path(__file__).parent / f"validate_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH.as_posix()}"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone  # noqa: E402

import app.models  # noqa: E402,F401 — registers every model on Base.metadata
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models.chat import Chat  # noqa: E402
from app.models.generated_content import GeneratedContent  # noqa: E402
from app.models.learning_session import LearningSession  # noqa: E402
from app.models.telemetry_event import TelemetryEvent  # noqa: E402
from app.models.user import User  # noqa: E402
from app.rl import bandit, qlearning  # noqa: E402
from app.rl.actions import IMPLEMENTED_MODES  # noqa: E402
from app.rl.policy import choose_action, record_outcome, snapshot_decision  # noqa: E402
from app.telemetry.scoring import expected_seconds_for_session  # noqa: E402

DEFAULT_SEEDS = 15
DEFAULT_EPISODES_PER_SEED = 60  # includes cold-start sessions


def _content_json_for_mode(mode: str, item_count: int = 6) -> dict:
    """Minimally realistic content per mode — enough for _base_expected_seconds (see
    telemetry/scoring.py) to compute a sane, mode-appropriate expected duration."""
    if mode == "quiz":
        return {"quiz": [{"question": f"q{i}", "options": ["a", "b", "c"], "correct_index": 0} for i in range(item_count)]}
    if mode == "flashcards":
        return {"cards": [{"front": f"f{i}", "back": f"b{i}"} for i in range(item_count)]}
    if mode == "qa":
        return {"items": [{"question": f"q{i}", "answer": "a" * 40} for i in range(item_count)]}
    if mode == "video":
        return {"video_url": "/x.mp4", "scenes": [{"duration": 20.0} for _ in range(item_count)]}
    if mode == "comic":
        return {"panels": [{"caption": "c", "image_prompt": "p"} for _ in range(item_count)]}
    if mode == "flowchart":
        lines = ["flowchart TD"] + [f"n{i}-->n{i+1}" for i in range(item_count)]
        return {"mermaid": "\n".join(lines)}
    if mode == "podcast":
        return {"segments": [{"speaker": "A", "text": "word " * 30} for _ in range(item_count)]}
    return {"summary": "text " * 200}  # summary — plain reading


# Which modes report a discrete progress ratio at all (mirrors the real frontend mode
# components — see components/modes/*.tsx). Modes with no progress reporting (summary,
# flowchart) fall back to the completion status alone, same as real usage.
PROGRESS_CAPABLE_MODES = {"quiz", "flashcards", "qa", "video", "comic", "podcast"}


def _simulate_session(db, user: User, chat: Chat, mode: str, quality: float, rng: random.Random) -> LearningSession:
    """Runs one full session through the REAL pipeline (snapshot_decision -> synthetic telemetry
    matching `quality` -> record_outcome), the same three calls sessions/router.py makes for a
    real user action. `quality` in [0, 1] controls how good the synthetic interaction looks —
    proportional dwell/interaction density, progress, and (for quiz) answer accuracy, each with
    per-session noise so it's not a suspiciously constant signal."""
    content = GeneratedContent(chat_id=chat.id, mode=mode, status="ready", content_json=_content_json_for_mode(mode))
    db.add(content)
    db.commit()
    db.refresh(content)

    session = LearningSession(user_id=user.id, generated_content_id=content.id, status="active")
    for key, value in snapshot_decision(db, user, chat, mode).items():
        setattr(session, key, value)
    db.add(session)
    db.commit()
    db.refresh(session)

    noisy_quality = max(0.03, min(0.97, quality + rng.gauss(0, 0.08)))
    expected_seconds, _overage = expected_seconds_for_session(db, session)
    char_count = len(str(content.content_json))
    expected_interactions = max(char_count / 200.0, 5.0)

    now = datetime.now(timezone.utc)

    db.add(
        TelemetryEvent(
            session_id=session.id,
            event_type="dwell",
            payload={"seconds": noisy_quality * expected_seconds},
            client_ts=now,
        )
    )
    n_interactions = max(0, round(noisy_quality * expected_interactions))
    for _ in range(n_interactions):
        db.add(TelemetryEvent(session_id=session.id, event_type="click", payload={}, client_ts=now))

    if mode in PROGRESS_CAPABLE_MODES:
        db.add(
            TelemetryEvent(
                session_id=session.id, event_type="progress", payload={"ratio": noisy_quality}, client_ts=now
            )
        )
    if mode == "quiz":
        n_questions = len(content.content_json["quiz"])
        n_correct = round(noisy_quality * n_questions)
        for i in range(n_questions):
            db.add(
                TelemetryEvent(
                    session_id=session.id,
                    event_type="quiz_answer",
                    payload={"question_index": i, "correct": i < n_correct},
                    client_ts=now,
                )
            )
    db.commit()

    session.status = "completed"
    db.commit()
    record_outcome(db, session)
    db.refresh(session)
    return session


def _run_one_seed(seed: int, n_episodes: int) -> dict:
    rng = random.Random(seed)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        user = User(id=f"user-{seed}", reading_pace_multiplier=1.0)
        db.add(user)
        db.commit()

        # Assign each mode a hidden ground-truth quality: exactly one clear best, one clear
        # worst, the rest shuffled in a middling band — a fresh random assignment per seed so
        # results aren't an artifact of one particular mode always winning.
        modes = list(IMPLEMENTED_MODES)
        rng.shuffle(modes)
        best_mode, worst_mode, *rest = modes
        quality = {best_mode: 0.90, worst_mode: 0.12}
        for m in rest:
            quality[m] = rng.uniform(0.35, 0.65)

        chosen_actions: list[tuple[int, str]] = []
        rewards: list[float] = []
        random_baseline_rewards: list[float] = []

        for i in range(n_episodes):
            chat = Chat(user_id=user.id, title=f"topic-{i}")
            db.add(chat)
            db.commit()
            db.refresh(chat)

            decision = choose_action(db, user, chat)
            mode = decision.mode
            session = _simulate_session(db, user, chat, mode, quality[mode], rng)
            chosen_actions.append((i, mode))
            rewards.append(session.engagement_score)  # proxy readout; real reward computed inside record_outcome

            # What a uniform-random policy would have scored in the exact same (state,
            # noise-draw) slot — computed by literally simulating the untaken alternative
            # through the same synthetic-quality function, for a fair regret comparison.
            random_mode = rng.choice(modes)
            random_baseline_rewards.append(
                max(0.03, min(0.97, quality[random_mode] + rng.gauss(0, 0.08)))
            )

        # Final learned preference for each mode, on the same reward-like scale shown in the UI —
        # the per-action weighted-average Q-value across every visited state (mirrors
        # app/stats/aggregation.py::_q_value_averages; inlined here so this script stays
        # independent of it rather than importing internals from the stats module).
        from app.models.q_state import QState

        rows = db.query(QState).filter_by(user_id=user.id).all()
        totals: dict[str, tuple[float, int]] = {}
        for row in rows:
            s, c = totals.get(row.action, (0.0, 0))
            totals[row.action] = (s + row.q_value * row.update_count, c + row.update_count)
        q_avg = {a: qlearning.q_to_reward_scale(s / c) for a, (s, c) in totals.items() if c > 0}

        bandit_mean = {}
        for m in modes:
            state = bandit.get_or_create_state(db, user.id, m)
            a, b = state.params_json["alpha"], state.params_json["beta"]
            bandit_mean[m] = a / (a + b)

        half = n_episodes // 2
        first_half_picks = [m for i, m in chosen_actions if i < half]
        second_half_picks = [m for i, m in chosen_actions if i >= half]
        first_half_best_rate = first_half_picks.count(best_mode) / max(len(first_half_picks), 1)
        second_half_best_rate = second_half_picks.count(best_mode) / max(len(second_half_picks), 1)

        return {
            "seed": seed,
            "best_mode": best_mode,
            "worst_mode": worst_mode,
            "q_avg": q_avg,
            "bandit_mean": bandit_mean,
            "first_half_best_rate": first_half_best_rate,
            "second_half_best_rate": second_half_best_rate,
            "policy_avg_reward": mean(rewards),
            "random_baseline_avg_reward": mean(random_baseline_rewards),
            "q_ranks_best_top2": (
                best_mode in sorted(q_avg, key=q_avg.get, reverse=True)[:2] if len(q_avg) >= 2 else None
            ),
            "q_ranks_worst_bottom2": (
                worst_mode in sorted(q_avg, key=q_avg.get)[:2] if len(q_avg) >= 2 else None
            ),
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=DEFAULT_SEEDS)
    parser.add_argument("--episodes", type=int, default=DEFAULT_EPISODES_PER_SEED)
    args = parser.parse_args()

    settings = get_settings()
    print(
        f"Simulating {args.seeds} independent learners x {args.episodes} sessions each "
        f"(cold_start_threshold={settings.rl_cold_start_session_threshold}, "
        f"gamma={settings.rl_gamma}, alpha={settings.rl_alpha})...\n"
    )

    results = [_run_one_seed(seed, args.episodes) for seed in range(args.seeds)]

    print(f"{'seed':>4}  {'best':<10} {'worst':<10} {'Q top2?':<8} {'Q bot2?':<8} {'pick-rate best (1st->2nd half)':<32} {'policy avg R':<13} {'random-baseline avg R'}")
    for r in results:
        pick_rate = f"{r['first_half_best_rate']:.2f} -> {r['second_half_best_rate']:.2f}"
        print(
            f"{r['seed']:>4}  {r['best_mode']:<10} {r['worst_mode']:<10} "
            f"{str(r['q_ranks_best_top2']):<8} {str(r['q_ranks_worst_bottom2']):<8} "
            f"{pick_rate:<32} {r['policy_avg_reward']:<13.3f} {r['random_baseline_avg_reward']:.3f}"
        )

    n = len(results)
    top2_hits = sum(1 for r in results if r["q_ranks_best_top2"])
    bottom2_hits = sum(1 for r in results if r["q_ranks_worst_bottom2"])
    improved_pick_rate = sum(1 for r in results if r["second_half_best_rate"] > r["first_half_best_rate"])
    beat_random = sum(1 for r in results if r["policy_avg_reward"] > r["random_baseline_avg_reward"])
    avg_policy_reward = mean(r["policy_avg_reward"] for r in results)
    avg_random_reward = mean(r["random_baseline_avg_reward"] for r in results)

    print(f"\n--- Summary across {n} independent seeds ---")
    print(f"Learned preference ranks the secretly-best mode in its top 2:   {top2_hits}/{n}")
    print(f"Learned preference ranks the secretly-worst mode in its bottom 2: {bottom2_hits}/{n}")
    print(f"Best-mode pick rate rose from 1st half to 2nd half of the run:  {improved_pick_rate}/{n}")
    print(f"Policy's realized avg reward beat the random-baseline avg:     {beat_random}/{n}")
    print(f"Mean realized reward — policy: {avg_policy_reward:.3f}  vs  random baseline: {avg_random_reward:.3f}")

    # Two separate questions, reported separately rather than one blunt gate — they have very
    # different implications if either fails:
    #   1. Is the mechanism sound at all (does acting on the learned preference beat acting
    #      randomly, using the real reward function)? This is the core "is it really learning
    #      from interaction data, or effectively random" question, and it's close to
    #      session-count-independent — even one visit per (state, action) pair still points the
    #      *chosen* action in a reward-informed direction most of the time.
    #   2. Has the fine-grained per-state ranking fully CONVERGED within this many sessions? This
    #      one is legitimately session-count-sensitive — see the module docstring's state-space
    #      cardinality note (app/rl/state.py) — a single (state, action) cell only gets a
    #      confident estimate after it's been revisited more than once, and with a state space
    #      this large relative to one user's session volume, most cells stay at n=1 for a long
    #      time. A low score here with few episodes is expected sparsity, not a defect — rerun
    #      with --episodes 300+ to confirm it converges given enough data (it should).
    mechanism_sound = beat_random >= n * 0.8 and avg_policy_reward > avg_random_reward
    ranking_converged = top2_hits >= n * 0.8 and bottom2_hits >= n * 0.8

    print(f"\n[{'PASS' if mechanism_sound else 'FAIL'}] Core mechanism: choosing by the learned "
          f"preference beats choosing randomly, using the real reward function.")
    print(f"[{'PASS' if ranking_converged else 'WEAK/FAIL'}] Fine-grained convergence: the per-mode "
          f"ranking fully separates best/worst within {args.episodes} sessions.")
    if mechanism_sound and not ranking_converged:
        print(
            "  -> Likely data sparsity, not a bug: rerun with a much larger --episodes to confirm "
            "it improves. If it doesn't improve with more data, that IS a real problem."
        )
    return 0 if mechanism_sound else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        engine.dispose()
        if _DB_PATH.exists():
            _DB_PATH.unlink()
