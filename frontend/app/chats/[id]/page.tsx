"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PendingSourceInput, SourceInputTabs } from "@/components/chat/SourceInputTabs";
import { TutorPanel } from "@/components/tutor/TutorPanel";
import {
  ApiError,
  addFileSource,
  addLinkSource,
  addTextSource,
  createSession,
  deleteSource,
  generateContent,
  getChat,
  getGeneratedContent,
  suggestMode,
} from "@/lib/api";
import type {
  ChatDetailOut,
  Difficulty,
  FlowchartOptions,
  GeneratedContentOut,
  Mode,
  PodcastOptions,
  QAOptions,
  QuestionCount,
  QuizFlashcardsOptions,
  SuggestModeOut,
  SummaryOptions,
} from "@/types/api";

const MODE_LABELS: Record<Mode, string> = {
  summary: "Summary",
  quiz: "Quiz",
  flashcards: "Flashcards",
  qa: "Q&A",
  flowchart: "Flowchart",
  podcast: "Podcast",
  comic: "Comic",
  video: "Video",
};

const MODE_ICONS: Record<Mode, string> = {
  summary: "📝",
  quiz: "🧠",
  flashcards: "🔁",
  qa: "💬",
  flowchart: "🗺️",
  podcast: "🎙️",
  comic: "🎨",
  video: "🎬",
};

// Labels the "Generating N of M..." progress text with the right unit per mode.
const PROGRESS_UNIT_LABELS: Partial<Record<Mode, string>> = {
  comic: "panel",
  video: "scene",
};

const IMPLEMENTED_MODES: Mode[] = ["summary", "quiz", "flashcards", "qa", "flowchart", "podcast", "comic", "video"];
const CONFIGURABLE_MODES: Mode[] = ["summary", "quiz", "flashcards", "qa", "flowchart", "podcast"];
const POLL_INTERVAL_MS = 2000;

// Podcast and flowchart are each a single Gemini call with no natural sub-steps to report real
// progress on the way comic/video do (those make one call per panel/scene). Instead, estimate
// how long the call should take from past runs and animate a progress bar off elapsed time,
// capped short of 100% so it never claims to be done before the response actually lands — an ETA
// countdown beats a frozen "Working..." while a demand-spike (503) retry loop rides itself out.
// Seconds are rough, calibrated from observed generation times; only entries here get the
// simulated bar, so the quick synchronous modes (summary/quiz/flashcards/qa) keep their plain
// "Working..." indicator.
const SIMULATED_PROGRESS_SECONDS: Partial<Record<Mode, (options?: object) => number>> = {
  podcast: (options) => ((options as PodcastOptions | undefined)?.length === "long" ? 40 : 15),
  flowchart: () => 12,
};
// Verb shown next to the % on the simulated bar, per mode.
const SIMULATED_PROGRESS_LABELS: Partial<Record<Mode, string>> = {
  podcast: "Writing script",
  flowchart: "Building diagram",
};
const SIMULATED_PROGRESS_TICK_MS = 300;
// Hard cap so the bar never visually claims 100% before the real response lands.
const SIMULATED_PROGRESS_CAP = 0.99;
// Tunes the exponential curve below so the bar sits around ~85% right at the estimated
// duration (-ln(1 - 0.85) ≈ 1.9), rather than an arbitrary constant.
const SIMULATED_PROGRESS_CURVE_K = 1.9;

function startSimulatedProgress(
  estimatedSeconds: number,
  setProgress: (p: {
    current: number;
    total: number;
    etaSeconds: number | null;
    simulated?: boolean;
    overrunning?: boolean;
  }) => void
): ReturnType<typeof setInterval> {
  const startedAt = Date.now();
  const tick = () => {
    const elapsedSeconds = (Date.now() - startedAt) / 1000;
    // Exponential approach toward 100% rather than a linear ramp hard-capped at a ceiling — a
    // linear-then-frozen bar looks broken once the real call runs past the estimate (which
    // Gemini often does), since both the percentage and the fill stop moving entirely. This
    // curve keeps creeping forward indefinitely, just slower over time, so there's always some
    // visible sign of life even during a long overrun.
    const fraction = Math.min(
      1 - Math.exp((-SIMULATED_PROGRESS_CURVE_K * elapsedSeconds) / estimatedSeconds),
      SIMULATED_PROGRESS_CAP
    );
    const overrunning = elapsedSeconds > estimatedSeconds;
    setProgress({
      current: Math.round(fraction * 100),
      total: 100,
      etaSeconds: overrunning ? null : Math.max(0, Math.round(estimatedSeconds - elapsedSeconds)),
      simulated: true,
      overrunning,
    });
  };
  tick();
  return setInterval(tick, SIMULATED_PROGRESS_TICK_MS);
}

const DIFFICULTIES: Difficulty[] = ["easy", "medium", "hard"];
const QUESTION_COUNTS: QuestionCount[] = [5, 10, 20];

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function formatEta(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m ${rest}s`;
}

// Short label for the *options a version was generated with* (e.g. "Med 10", "Deep dive") —
// the same wording as the config panel's own pills, so a version in the "earlier versions" list
// reads the same as the choice that made it. Returns null for options this mode doesn't have a
// short form for.
function formatOptionsLabel(mode: Mode, options: Record<string, unknown> | null): string | null {
  if (!options) return null;
  switch (mode) {
    case "quiz":
    case "flashcards": {
      const difficulty = options.difficulty;
      const count = options.num_questions;
      if (typeof difficulty !== "string" || typeof count !== "number") return null;
      const diffLabel = { easy: "Easy", medium: "Med", hard: "Hard" }[difficulty] ?? difficulty;
      return `${diffLabel} ${count}`;
    }
    case "summary": {
      const length = options.length;
      if (length === "detailed") return "Detailed";
      if (length === "concise") return "Concise";
      return null;
    }
    case "qa": {
      const count = options.num_questions;
      const style = options.answer_style;
      if (typeof count !== "number" || typeof style !== "string") return null;
      return `${count} · ${style === "short" ? "Short" : "Long"}`;
    }
    case "podcast": {
      const length = options.length;
      if (length === "long") return "Deep dive";
      if (length === "short") return "Quick overview";
      return null;
    }
    case "flowchart": {
      const diagram = options.diagram;
      if (diagram === "mindmap") return "Mindmap";
      if (diagram === "flowchart") return "Flowchart";
      return null;
    }
    default:
      return null;
  }
}

// Every past generation stays in the DB forever (GeneratedContent rows are never deleted) — this
// maps each one (for a single mode, newest-first) to a label for the "earlier versions" list.
// Versions that share the exact same options (e.g. two "Med 5" quizzes) get " v1"/" v2" suffixes,
// numbered in the order they were actually created, so they're still distinguishable — a bare
// "Med 5" repeated with no way to tell them apart wouldn't actually help pick one.
function buildVersionLabels(mode: Mode, generationsNewestFirst: GeneratedContentOut[]): Map<string, string> {
  const ascending = generationsNewestFirst.slice().reverse();
  const totalByKey = new Map<string, number>();
  for (const g of ascending) {
    const key = formatOptionsLabel(mode, g.options_json) ?? "Version";
    totalByKey.set(key, (totalByKey.get(key) ?? 0) + 1);
  }

  const seenByKey = new Map<string, number>();
  const labels = new Map<string, string>();
  for (const g of ascending) {
    const key = formatOptionsLabel(mode, g.options_json) ?? "Version";
    const ordinal = (seenByKey.get(key) ?? 0) + 1;
    seenByKey.set(key, ordinal);
    const optionsLabel = totalByKey.get(key)! > 1 ? `${key} v${ordinal}` : key;

    const when = new Date(g.created_at).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    const cj = g.content_json as { title?: unknown } | null;
    const title = cj && typeof cj === "object" && typeof cj.title === "string" ? cj.title : null;
    labels.set(g.id, [optionsLabel, title, when].filter(Boolean).join(" · "));
  }
  return labels;
}

function PillGroup<T extends string | number>({
  options,
  value,
  labels,
  onChange,
}: {
  options: T[];
  value: T;
  labels?: Partial<Record<T, string>>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="pill-group">
      {options.map((opt) => (
        <button
          key={String(opt)}
          type="button"
          className={`option-pill ${value === opt ? "selected" : ""}`}
          onClick={() => onChange(opt)}
        >
          {labels?.[opt] ?? String(opt)}
        </button>
      ))}
    </div>
  );
}

export default function ChatPage({ params }: { params: { id: string } }) {
  const chatId = params.id;
  const router = useRouter();
  const searchParams = useSearchParams();
  const deepLinkedModeRef = useRef<string | null>(null);
  // Backs the corner "⋯" overflow menu (Regenerate / earlier versions) on configurable mode
  // cards — a plain uncontrolled <details>, closed manually after picking an item so it doesn't
  // stay floating open once its action (opening the config panel, navigating to a session) fires.
  const modeMenuRefs = useRef<Partial<Record<Mode, HTMLDetailsElement | null>>>({});
  const closeModeMenu = (mode: Mode) => {
    const el = modeMenuRefs.current[mode];
    if (el) el.open = false;
  };

  const [detail, setDetail] = useState<ChatDetailOut | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestModeOut | null>(null);
  const [busyMode, setBusyMode] = useState<Mode | null>(null);
  const [progress, setProgress] = useState<{
    current: number;
    total: number;
    etaSeconds: number | null;
    simulated?: boolean;
    overrunning?: boolean;
  } | null>(null);
  const [removingSourceId, setRemovingSourceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollStartedAtRef = useRef<number | null>(null);

  const [configuringMode, setConfiguringMode] = useState<Mode | null>(null);
  const [quizOptions, setQuizOptions] = useState<QuizFlashcardsOptions>({ difficulty: "medium", num_questions: 10 });
  const [flashcardsOptions, setFlashcardsOptions] = useState<QuizFlashcardsOptions>({
    difficulty: "medium",
    num_questions: 10,
  });
  const [summaryOptions, setSummaryOptions] = useState<SummaryOptions>({ length: "concise" });
  const [qaOptions, setQaOptions] = useState<QAOptions>({ num_questions: 10, answer_style: "long" });
  const [podcastOptions, setPodcastOptions] = useState<PodcastOptions>({ length: "short" });
  const [flowchartOptions, setFlowchartOptions] = useState<FlowchartOptions>({ diagram: "flowchart" });

  const refresh = () => {
    Promise.all([getChat(chatId), suggestMode(chatId)])
      .then(([d, s]) => {
        setDetail(d);
        setSuggestion(s);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load chat."));
  };

  useEffect(refresh, [chatId]);

  const onAddSource = async (input: PendingSourceInput) => {
    setError(null);
    try {
      if (input.type === "pdf" || input.type === "txt") {
        await addFileSource(chatId, input.file);
      } else if (input.type === "youtube" || input.type === "website") {
        await addLinkSource(chatId, input.type, input.url);
      } else {
        await addTextSource(chatId, input.text);
      }
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add that source.");
    }
  };

  const onRemoveSource = async (sourceId: string) => {
    setError(null);
    setRemovingSourceId(sourceId);
    try {
      await deleteSource(chatId, sourceId);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove that source.");
    } finally {
      setRemovingSourceId(null);
    }
  };

  // Comic and video generation run in the background on the server (per-panel/per-scene
  // images, plus narration + muxing for video, can take minutes). They come back with status
  // "pending" — poll until ready or failed, surfacing step-by-step progress instead of a frozen
  // button.
  const pollUntilDone = async (contentId: string): Promise<GeneratedContentOut> => {
    pollStartedAtRef.current = Date.now();
    while (true) {
      const content = await getGeneratedContent(contentId);
      if (content.status === "ready") {
        setProgress(null);
        return content;
      }
      if (content.status === "failed") {
        setProgress(null);
        throw new Error(content.error_message || "Generation failed.");
      }
      if (content.progress_current !== null && content.progress_total !== null) {
        const current = content.progress_current;
        const total = content.progress_total;
        const startedAt = pollStartedAtRef.current;
        let etaSeconds: number | null = null;
        if (startedAt && current > 0) {
          const elapsedMs = Date.now() - startedAt;
          const estimatedTotalMs = (elapsedMs / current) * total;
          etaSeconds = Math.max(0, Math.round((estimatedTotalMs - elapsedMs) / 1000));
        }
        setProgress({ current, total, etaSeconds });
      }
      await sleep(POLL_INTERVAL_MS);
    }
  };

  const onPickMode = async (mode: Mode, options?: object) => {
    setError(null);

    if (!IMPLEMENTED_MODES.includes(mode)) {
      setError(`${MODE_LABELS[mode]} isn't implemented yet — coming in a later phase.`);
      return;
    }

    setBusyMode(mode);
    setProgress(null);
    setConfiguringMode(null);
    let simInterval: ReturnType<typeof setInterval> | null = null;
    try {
      // Explicit options means the user just configured this generation on purpose — always
      // generate fresh rather than silently reusing a previous run with different settings.
      const existing = options ? undefined : detail?.generations.filter((g) => g.mode === mode && g.status === "ready").pop();

      const estimatedSeconds = existing ? undefined : SIMULATED_PROGRESS_SECONDS[mode]?.(options);
      if (estimatedSeconds) {
        simInterval = startSimulatedProgress(estimatedSeconds, setProgress);
      }

      let content = existing ?? (await generateContent(chatId, mode, options));
      if (simInterval) {
        clearInterval(simInterval);
        simInterval = null;
      }
      if (content.status === "pending") {
        content = await pollUntilDone(content.id);
      }
      const session = await createSession(content.id);
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Generation failed.");
    } finally {
      if (simInterval) clearInterval(simInterval);
      setBusyMode(null);
      setProgress(null);
    }
  };

  // Opens one specific past generation directly (no Gemini call at all) — used by the "earlier
  // versions" list on configurable mode cards, so an older podcast/quiz/etc. a user regenerated
  // over stays reachable instead of only ever the latest one.
  const onResumeContent = async (content: GeneratedContentOut) => {
    setError(null);
    setBusyMode(content.mode);
    try {
      const session = await createSession(content.id);
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Could not open that version.");
    } finally {
      setBusyMode(null);
    }
  };

  // Deep link from the "still with it?" check-in popup (e.g. /chats/x?mode=comic) — jump
  // straight into that mode instead of making the user find it in the grid again. Runs once
  // per page load, after sources/generations have loaded so onPickMode can reuse an existing
  // ready generation if there is one.
  useEffect(() => {
    const requestedMode = searchParams.get("mode") as Mode | null;
    if (!requestedMode || !detail || deepLinkedModeRef.current === requestedMode) return;
    deepLinkedModeRef.current = requestedMode;
    if (!IMPLEMENTED_MODES.includes(requestedMode)) return;
    const hasReady = detail.generations.some((g) => g.mode === requestedMode && g.status === "ready");
    if (CONFIGURABLE_MODES.includes(requestedMode) && !hasReady) {
      setConfiguringMode(requestedMode);
    } else {
      onPickMode(requestedMode);
    }
  }, [searchParams, detail]);

  if (error && !detail) return <p className="error-text page">{error}</p>;
  if (!detail) return <p className="page">Loading...</p>;

  return (
    <div className="chat-layout">
      <div className="chat-main">
      <h1>{detail.chat.title || "Untitled chat"}</h1>

      <h2>Sources</h2>
      <div className="source-chips">
        {detail.sources.map((source) => (
          <div className={`source-chip ${source.status}`} key={source.id}>
            <span>
              <span className="source-chip-type">{source.source_type}</span>
              {source.original_ref}
            </span>
            <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <span className={`source-status-badge ${source.status}`}>{source.status}</span>
              <button
                className="source-chip-remove"
                onClick={() => onRemoveSource(source.id)}
                disabled={removingSourceId === source.id}
                title="Remove this source"
              >
                {removingSourceId === source.id ? "…" : "×"}
              </button>
            </span>
          </div>
        ))}
        {detail.sources.length === 0 && <p className="text-muted">No sources yet — add one below.</p>}
      </div>
      <SourceInputTabs onAdd={onAddSource} />

      <h2>How do you want to learn this?</h2>
      {suggestion && (
        <p style={{ color: "var(--accent-strong)" }}>
          Suggested for you: <strong>{MODE_LABELS[suggestion.mode]}</strong> (confidence{" "}
          {(suggestion.confidence * 100).toFixed(0)}%)
          {suggestion.policy === "cold_start_thompson" && (
            <span className="text-muted" style={{ fontSize: 12 }}>
              {" "}
              · still exploring what works for you
            </span>
          )}
        </p>
      )}

      <div className="mode-grid">
        {(Object.keys(MODE_LABELS) as Mode[]).map((mode) => {
          // Newest first — the backend returns generations in created_at ascending order, so
          // reversing gives newest-first without re-sorting. readyGenerations[0] is what a plain
          // click resumes; the rest are the "earlier versions" a regenerate would otherwise hide.
          const readyGenerations = detail.generations
            .filter((g) => g.mode === mode && g.status === "ready")
            .slice()
            .reverse();
          const hasReady = readyGenerations.length > 0;
          const isConfigurable = CONFIGURABLE_MODES.includes(mode);
          const isImplemented = IMPLEMENTED_MODES.includes(mode);
          const isBusy = busyMode !== null;
          const versionLabels = isConfigurable ? buildVersionLabels(mode, readyGenerations) : null;

          const onCardActivate = () => {
            if (isBusy || !isImplemented) return;
            if (isConfigurable && !hasReady) {
              setConfiguringMode((prev) => (prev === mode ? null : mode));
            } else {
              // Either not configurable (comic/video always just resume-or-generate), or
              // configurable with a ready generation to resume — either way onPickMode's own
              // "existing" lookup (no options passed) picks up the latest ready one for free.
              onPickMode(mode);
            }
          };

          return (
            <div
              key={mode}
              role="button"
              tabIndex={isBusy || !isImplemented ? -1 : 0}
              className={`mode-card ${suggestion?.mode === mode ? "suggested" : ""} ${
                configuringMode === mode ? "configuring" : ""
              } ${isBusy ? "busy" : ""}`}
              onClick={onCardActivate}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onCardActivate();
                }
              }}
              aria-disabled={isBusy || !isImplemented}
              data-disabled={!isImplemented}
            >
              {suggestion?.mode === mode && <span className="badge">Suggested</span>}
              <div style={{ fontSize: 22, marginBottom: 4 }}>{MODE_ICONS[mode]}</div>
              <div style={{ fontWeight: 600 }}>{MODE_LABELS[mode]}</div>
              {!isImplemented && <div className="text-muted" style={{ fontSize: 12 }}>Coming soon</div>}
              {isImplemented && (
                <div className="text-muted" style={{ fontSize: 12 }}>
                  {hasReady ? "Start learning" : isConfigurable ? "Configure & generate" : "Generate"}
                </div>
              )}
              {isImplemented && isConfigurable && hasReady && (
                <details
                  className="mode-card-menu"
                  onClick={(e) => e.stopPropagation()}
                  ref={(el) => {
                    modeMenuRefs.current[mode] = el;
                  }}
                >
                  <summary title="Regenerate or open an earlier version">⋯</summary>
                  <div className="mode-card-menu-content">
                    <button
                      type="button"
                      className="mode-card-menu-item"
                      disabled={isBusy}
                      onClick={() => {
                        closeModeMenu(mode);
                        setConfiguringMode((prev) => (prev === mode ? null : mode));
                      }}
                    >
                      ⟳ Regenerate
                    </button>
                    {readyGenerations.length > 1 && (
                      <>
                        <div className="mode-card-menu-divider" />
                        <div className="mode-card-menu-label">Earlier versions</div>
                        {readyGenerations.slice(1).map((g) => (
                          <button
                            key={g.id}
                            type="button"
                            className="mode-card-menu-item"
                            disabled={isBusy}
                            onClick={() => {
                              closeModeMenu(mode);
                              onResumeContent(g);
                            }}
                          >
                            {versionLabels?.get(g.id) ?? g.id}
                          </button>
                        ))}
                      </>
                    )}
                  </div>
                </details>
              )}
              {busyMode === mode && (
                <div className="gen-progress">
                  {progress ? (
                    <>
                      <div className="progress-bar-track">
                        <div
                          className={`progress-bar-fill ${progress.simulated ? "progress-bar-fill-simulated" : ""}`}
                          style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                        />
                      </div>
                      <div className="progress-bar-label">
                        {progress.simulated ? (
                          <>
                            {SIMULATED_PROGRESS_LABELS[mode] ?? "Generating"}...{" "}
                            {Math.round((progress.current / progress.total) * 100)}%
                            {progress.overrunning
                              ? " · taking longer than usual, still working..."
                              : progress.etaSeconds !== null && progress.etaSeconds > 0
                              ? ` · ~${formatEta(progress.etaSeconds)} left`
                              : ""}
                          </>
                        ) : (
                          <>
                            {Math.round((progress.current / progress.total) * 100)}% ·{" "}
                            {PROGRESS_UNIT_LABELS[mode] ?? "step"} {progress.current}/{progress.total}
                            {progress.etaSeconds !== null && progress.etaSeconds > 0
                              ? ` · ~${formatEta(progress.etaSeconds)} left`
                              : ""}
                          </>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className="text-muted" style={{ fontSize: 12 }}>
                      Working...
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {configuringMode === "quiz" && (
        <div className="mode-config-panel">
          <h3>Quiz options</h3>
          <div className="option-row">
            <span className="option-row-label">Difficulty</span>
            <PillGroup
              options={DIFFICULTIES}
              value={quizOptions.difficulty}
              onChange={(v) => setQuizOptions((o) => ({ ...o, difficulty: v }))}
            />
          </div>
          <div className="option-row">
            <span className="option-row-label">Number of questions</span>
            <PillGroup
              options={QUESTION_COUNTS}
              value={quizOptions.num_questions}
              onChange={(v) => setQuizOptions((o) => ({ ...o, num_questions: v }))}
            />
          </div>
          <div className="mode-config-actions">
            <button className="btn" onClick={() => onPickMode("quiz", quizOptions)} disabled={busyMode !== null}>
              Generate quiz
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {configuringMode === "flashcards" && (
        <div className="mode-config-panel">
          <h3>Flashcards options</h3>
          <div className="option-row">
            <span className="option-row-label">Difficulty</span>
            <PillGroup
              options={DIFFICULTIES}
              value={flashcardsOptions.difficulty}
              onChange={(v) => setFlashcardsOptions((o) => ({ ...o, difficulty: v }))}
            />
          </div>
          <div className="option-row">
            <span className="option-row-label">Number of cards</span>
            <PillGroup
              options={QUESTION_COUNTS}
              value={flashcardsOptions.num_questions}
              onChange={(v) => setFlashcardsOptions((o) => ({ ...o, num_questions: v }))}
            />
          </div>
          <div className="mode-config-actions">
            <button
              className="btn"
              onClick={() => onPickMode("flashcards", flashcardsOptions)}
              disabled={busyMode !== null}
            >
              Generate flashcards
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {configuringMode === "summary" && (
        <div className="mode-config-panel">
          <h3>Summary options</h3>
          <div className="option-row">
            <span className="option-row-label">Length</span>
            <PillGroup
              options={["concise", "detailed"] as const}
              value={summaryOptions.length}
              labels={{ concise: "Short & concise", detailed: "Detailed" }}
              onChange={(v) => setSummaryOptions({ length: v })}
            />
          </div>
          <div className="mode-config-actions">
            <button className="btn" onClick={() => onPickMode("summary", summaryOptions)} disabled={busyMode !== null}>
              Generate summary
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {configuringMode === "qa" && (
        <div className="mode-config-panel">
          <h3>Q&amp;A options</h3>
          <div className="option-row">
            <span className="option-row-label">Number of questions</span>
            <PillGroup
              options={QUESTION_COUNTS}
              value={qaOptions.num_questions}
              onChange={(v) => setQaOptions((o) => ({ ...o, num_questions: v }))}
            />
          </div>
          <div className="option-row">
            <span className="option-row-label">Answer style</span>
            <PillGroup
              options={["short", "long"] as const}
              value={qaOptions.answer_style}
              labels={{ short: "Short answers", long: "Long, descriptive" }}
              onChange={(v) => setQaOptions((o) => ({ ...o, answer_style: v }))}
            />
          </div>
          <div className="mode-config-actions">
            <button className="btn" onClick={() => onPickMode("qa", qaOptions)} disabled={busyMode !== null}>
              Generate Q&amp;A
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {configuringMode === "podcast" && (
        <div className="mode-config-panel">
          <h3>Podcast options</h3>
          <div className="option-row">
            <span className="option-row-label">Episode length</span>
            <PillGroup
              options={["short", "long"] as const}
              value={podcastOptions.length}
              labels={{ short: "Quick overview", long: "Deep dive" }}
              onChange={(v) => setPodcastOptions({ length: v })}
            />
          </div>
          <div className="mode-config-actions">
            <button className="btn" onClick={() => onPickMode("podcast", podcastOptions)} disabled={busyMode !== null}>
              Generate podcast
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {configuringMode === "flowchart" && (
        <div className="mode-config-panel">
          <h3>Flowchart options</h3>
          <div className="option-row">
            <span className="option-row-label">Diagram style</span>
            <PillGroup
              options={["flowchart", "mindmap"] as const}
              value={flowchartOptions.diagram}
              labels={{ flowchart: "Flowchart", mindmap: "Mindmap" }}
              onChange={(v) => setFlowchartOptions({ diagram: v })}
            />
          </div>
          <div className="mode-config-actions">
            <button className="btn" onClick={() => onPickMode("flowchart", flowchartOptions)} disabled={busyMode !== null}>
              Generate diagram
            </button>
            <button className="btn-secondary" onClick={() => setConfiguringMode(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && <p className="error-text">{error}</p>}
      </div>
      <TutorPanel chatId={chatId} />
    </div>
  );
}
