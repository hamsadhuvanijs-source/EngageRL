# EngageRL

Upload study material and learn it the way that works best for you. A contextual bandit
watches how engaged you are with each generated format (summary+quiz, flowchart, podcast,
comic/animated clip) and learns which one to suggest next time.

Only **Summary + Quiz** is implemented right now. Flowchart, Podcast, and Comic are wired up
as stubs (they return a clean "not implemented yet" instead of crashing) so they can be built
out later behind the same interface.

## Prerequisites

- Python 3.10+
- Node.js 18+
- A [Gemini API key](https://aistudio.google.com/apikey) (only needed to actually generate
  summaries/quizzes — everything else works without one)

## Setup

```bash
# from the repo root
cp .env.example .env
# edit .env and set GEMINI_API_KEY=...
```

Get a Gemini API key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
alembic upgrade head          # creates backend/app.db
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

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
3. Click **Create Chat**. You land on the chat view — its sources, the bandit's suggested mode,
   and a mode grid.
4. Pick **Summary + Quiz**. This calls Gemini to generate a summary and 5 quiz questions from
   the combined text of all the chat's sources.
5. While you read/answer, the page is quietly tracking tab switches, scroll, keypresses,
   mouse activity, and dwell time.
6. Click **Mark as complete**. The backend scores your engagement (0-1) and folds it into
   the bandit's per-mode `Beta(alpha, beta)` parameters for your (implicit, single) user.
7. Back on the dashboard: your engagement trend, per-mode learning-style preference, and this
   chat now show up. Start another chat and watch the suggested mode shift over a few rounds.

## Architecture

```
backend/app/
  chats/        chat CRUD (a "chat" = one bundle of reference sources on one topic)
  ingestion/    per-chat source endpoints: PDF/TXT upload, YouTube transcript, website
                scraping (trafilatura), pasted text — extraction + chunking
  generation/   one generator per mode behind GeneratorInterface; only summary_quiz is
                implemented, combining all of a chat's extracted sources before calling Gemini
  telemetry/    event ingestion + compute_engagement_score()
  rl/           Thompson Sampling bandit (Beta-Bernoulli per user+mode), suggest/update,
                session-end hook
  sessions/     learning session lifecycle
  stats/        dashboard aggregation (activity, engagement trend, mode preference, recents)
frontend/
  app/                     stats dashboard (/) -> new chat composer -> chat view -> session viewer
  components/shell/        persistent Sidebar (New Chat + chat history) + AppShell layout
  components/chat/         SourceInputTabs (file/YouTube/website/paste-text), SourceComposer
  components/stats/        dashboard tiles, engagement-trend chart, mode-preference bars
  components/telemetry/    TelemetryProvider: browser-only signal capture (Page Visibility,
                            scroll/key/mouse listeners), batched POSTs to the backend
  components/modes/        one view component per mode (others are "coming soon" stubs)
```

See the engagement-score formula in `backend/app/telemetry/scoring.py` and the bandit in
`backend/app/rl/bandit.py` — both are deliberately simple and readable rather than tuned.

## Known gaps (by design, for this pass)

- No auth — everything belongs to one implicit local user (`app/deps.py`).
- SQLite for local dev; models avoid SQLite-only types so swapping to Postgres later is just
  a `DATABASE_URL` change.
- Flowchart, Podcast, and Comic modes are unimplemented stubs.
- YouTube transcript fetching can be blocked by some networks (datacenter/cloud IPs in
  particular) — it's a real implementation, not a stub, but not 100% reliable everywhere.
- The bandit doesn't yet condition on context (source length/type) — `rl/context.py` computes
  a bucket but it isn't wired into arm selection yet; that's the next step toward a true
  contextual bandit.
