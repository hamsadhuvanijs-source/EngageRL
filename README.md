# EngageRL

Upload study material and learn it the way that works best for you. A tabular Q-learning agent
watches how you engage with each generated format (summary, quiz, flashcards, Q&A, comic,
video) and learns, from real telemetry, which format actually helps *you* learn — not just
which one you happened to click on.

**Summary, Quiz, Flashcards, Q&A, Comic, and Video are implemented.** Flowchart and Podcast are
wired up as stubs (a clean "not implemented yet" instead of crashing) so they can be built out
later behind the same interface — they're deliberately excluded from the RL action space until
then (see `backend/app/rl/actions.py`).

## Prerequisites

- Python 3.10+
- Node.js 18+
- A [Gemini API key](https://aistudio.google.com/apikey) (needed for all six generated formats)
- FFmpeg on PATH (video mode muxes audio+images into an mp4 via moviepy)

## Setup

```bash
# from the repo root
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
alembic upgrade head          # creates/updates backend/app.db
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

Run the test suite (isolated SQLite file per run, never touches `app.db`):

```bash
cd backend
pytest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

App: http://localhost:3000

## Walking through it

1. Open http://localhost:3000 — you land on your stats dashboard (empty at first).
2. Click **New Chat** in the sidebar. Add 2-3 reference sources on one topic: upload a PDF/TXT,
   paste a YouTube link, paste a website link, or paste raw text. Each becomes a removable chip.
3. Click **Create Chat**. You land on the chat view — its sources, the RL policy's suggested
   mode, and a mode grid to pick any format yourself.
4. Pick a mode (or follow the suggestion). This calls Gemini to generate that format from the
   combined text of all the chat's sources.
5. While you study, the page is quietly tracking tab switches, scroll, keypresses, mouse
   activity, dwell time, per-item progress (questions answered, cards seen, video watched, ...),
   quiz correctness, and — via a couple of small non-blocking check-ins — whether you're
   actually enjoying this format and, if you finish early, why.
6. Click **Mark as complete**. The backend scores the session, turns that into a learning
   reward, computes your resulting state, and runs a real Q-learning update.
7. Back on the dashboard: your engagement trend, per-mode learning preference (now Q-value
   based once you're past cold start), and this chat show up. Start a few more sessions and
   watch the suggestion adapt to how you're actually doing, not just which mode "won" overall.

## How the RL actually works

This is an **MDP-based tabular Q-learning system**, not a contextual bandit — the previous
Thompson-sampling bandit is kept, but strictly as a cold-start fallback (see below), not as the
long-term policy. If you're evaluating this project: the action selection that matters, once a
user has any real history, comes from `Q(s, a)` over an explicit learner state, updated with the
standard Bellman equation — not from a per-mode win-rate.

**State** (`backend/app/rl/state.py`) — 6 discretized features built from telemetry that's
already collected elsewhere in the app (nothing invented just for RL):

| Feature | Values | Source |
|---|---|---|
| `engagement` | low / medium / high | rolling avg of recent `engagement_score` (itself already a blend of dwell time, interaction rate, tab switching, completion, and self-reported feedback) |
| `progress` | low / medium / high | rolling avg of recent raw completion ratios |
| `pace` | fast / normal / slow | the user's `reading_pace_multiplier` |
| `quiz_accuracy` | low / medium / high / none | rolling accuracy over recent quiz sessions |
| `last_mode` | one of 6 modes / none | most recent mode used *within the current chat* (episode-local recent-format history) |
| `content_length` | short / medium / long | reuses `rl/context.py`'s previously-unused source-length bucket |

Cardinality is bounded (3×3×3×4×7×3 = 2268 possible states) so the table stays tractable for
tabular Q-learning, while in practice only a sparse fraction is ever visited by one user's real
history — unvisited `(state, action)` pairs simply have no row and are treated as `Q = 0`.

**Actions** — the 6 implemented modes (`rl/actions.py`), not the full mode list; an unimplemented
generator can never be selected.

**Reward** (`backend/app/rl/reward.py`) — built on top of the existing engagement score (which
already resists "just spend more time on the page": dwell time gets full credit up to the
expected pace and decays past a grace threshold unless interaction density holds up), plus:
- a quiz-accuracy component where applicable, and
- an improvement component comparing this session against the learner's own recent baseline —

so getting *better* is rewarded, not just being engaged in the moment.

**Episodes** — one learning topic (`Chat`) is one episode. A session transition is terminal
(`done=True`) when it looks like real mastery: high completion, strong quiz accuracy (if
applicable), solid engagement (`reward.py::is_topic_mastered` — a documented heuristic, not a
ground-truth signal, since there's no explicit "I'm done with this topic" action yet).

**The update** (`backend/app/rl/qlearning.py`), exactly the standard rule:

```
Q(s,a) <- Q(s,a) + alpha * [reward + gamma * max_a' Q(s',a') - Q(s,a)]
```

with the bootstrapped term dropped on terminal transitions. Epsilon-greedy selection, epsilon
decaying with the user's Q-learning experience. `alpha`, `gamma`, `epsilon_start/min/decay`, and
the cold-start threshold are all configurable via `app/config.py` / env vars.

**Cold start** — a brand-new user's Q-table is empty, so per-state action-values would just be
meaningless ties. For a user's first few sessions (`rl_cold_start_session_threshold`), action
*selection* falls back to the old Thompson-sampling bandit (`rl/bandit.py`) instead. Critically,
Q-learning is off-policy: **every** real transition — cold-start-chosen or Q-learning-chosen or
just picked freely from the mode grid — still gets recorded and folded into the Q-table. So by
the time cold start ends, the table already has real experience instead of starting blank.

**Persistence** — the Q-table (`q_state`) and the full transition history (`rl_transitions`,
one row per completed session: state, action, reward, next_state, done, which policy chose it)
both live in the same SQLite/Postgres database as everything else. Nothing about the learning
is in-memory-only; it survives restarts. `GET /rl/policy-state` exposes the current regime, the
full Q-table, and recent transitions for debugging.

## Architecture

```
backend/app/
  chats/        chat CRUD (a "chat" = one bundle of reference sources on one topic = one RL episode)
  ingestion/    per-chat source endpoints: PDF/TXT upload, YouTube transcript, website
                scraping (trafilatura), pasted text — extraction + chunking
  generation/   one generator per mode behind GeneratorInterface (summary, quiz, flashcards,
                qa, comic, video implemented; flowchart/podcast stubbed)
  telemetry/    event ingestion + compute_engagement_score() (dwell/interaction/tab/completion/feedback)
  rl/
    actions.py    the implemented action space (single source of truth)
    state.py      learner-state construction & discretization
    reward.py     learning reward + episode-termination (mastery) heuristic
    qlearning.py  tabular Q-table access, Bellman update, epsilon-greedy selection
    policy.py     hybrid orchestrator: cold-start Thompson vs Q-learning, snapshot/record hooks
    bandit.py     Thompson sampling — cold-start policy ONLY, not the main policy
    context.py    source-length bucketing, reused by state.py
    hooks.py      session-completion entry point used by sessions/router.py
    router.py     /chats/{id}/suggest-mode, /rl/policy-state
  sessions/     learning session lifecycle — snapshots RL state+action at creation, records the
                full transition and runs the Q-update at completion
  stats/        dashboard aggregation (activity, engagement trend, Q-value-based mode
                preference, recents, active RL policy)
frontend/
  app/                     stats dashboard (/) -> new chat composer -> chat view -> session viewer
  components/shell/        persistent Sidebar (New Chat + chat history) + AppShell layout
  components/chat/         SourceInputTabs (file/YouTube/website/paste-text), SourceComposer
  components/stats/        dashboard tiles, engagement-trend chart, mode-preference bars
  components/telemetry/    TelemetryProvider: browser-only signal capture (Page Visibility,
                            scroll/key/mouse listeners, per-item progress, quiz correctness,
                            enjoyment feedback), batched POSTs to the backend
  components/session/      "still with it?" check-in, mid/end-session enjoyment prompt
  components/modes/        one view component per implemented mode
```

Backend tests live in `backend/tests/` (`pytest`) — state discretization, reward shaping,
Q-learning updates/epsilon-greedy/terminal handling, and a full snapshot→interact→record
end-to-end flow through the real entry points.

## Known gaps (by design, for this pass)

- No auth — everything belongs to one implicit local user (`app/deps.py`); the RL code itself
  takes `user_id` as a parameter throughout rather than hardcoding this, so multi-user support
  is mostly a `deps.py` change away.
- SQLite for local dev; models avoid SQLite-only types so swapping to Postgres later is just
  a `DATABASE_URL` change.
- Flowchart and Podcast modes are unimplemented stubs, and excluded from the RL action space
  until they are.
- YouTube transcript fetching can be blocked by some networks (datacenter/cloud IPs in
  particular) — it's a real implementation, not a stub, but not 100% reliable everywhere.
- The "topic mastered" terminal-state check (`rl/reward.py::is_topic_mastered`) is a heuristic
  over completion/accuracy/engagement, not an explicit "I'm done with this topic" user action —
  a natural follow-up if this needs to be more precise.
