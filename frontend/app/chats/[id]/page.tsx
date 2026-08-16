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
  GeneratedContentOut,
  Mode,
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

const IMPLEMENTED_MODES: Mode[] = ["summary", "quiz", "flashcards", "qa", "comic", "video"];
const CONFIGURABLE_MODES: Mode[] = ["summary", "quiz", "flashcards", "qa"];
const POLL_INTERVAL_MS = 2000;

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

  const [detail, setDetail] = useState<ChatDetailOut | null>(null);
  const [suggestion, setSuggestion] = useState<SuggestModeOut | null>(null);
  const [busyMode, setBusyMode] = useState<Mode | null>(null);
  const [progress, setProgress] = useState<{ current: number; total: number; etaSeconds: number | null } | null>(
    null
  );
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
    try {
      // Explicit options means the user just configured this generation on purpose — always
      // generate fresh rather than silently reusing a previous run with different settings.
      const existing = options ? undefined : detail?.generations.filter((g) => g.mode === mode && g.status === "ready").pop();
      let content = existing ?? (await generateContent(chatId, mode, options));
      if (content.status === "pending") {
        content = await pollUntilDone(content.id);
      }
      const session = await createSession(content.id);
      router.push(`/sessions/${session.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Generation failed.");
    } finally {
      setBusyMode(null);
      setProgress(null);
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
    if (CONFIGURABLE_MODES.includes(requestedMode)) {
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
        </p>
      )}

      <div className="mode-grid">
        {(Object.keys(MODE_LABELS) as Mode[]).map((mode) => {
          const hasReady = detail.generations.some((g) => g.mode === mode && g.status === "ready");
          return (
            <button
              key={mode}
              className={`mode-card ${suggestion?.mode === mode ? "suggested" : ""} ${
                configuringMode === mode ? "configuring" : ""
              }`}
              onClick={() => {
                if (CONFIGURABLE_MODES.includes(mode)) {
                  setConfiguringMode((prev) => (prev === mode ? null : mode));
                } else {
                  onPickMode(mode);
                }
              }}
              disabled={busyMode !== null}
              data-disabled={!IMPLEMENTED_MODES.includes(mode)}
            >
              {suggestion?.mode === mode && <span className="badge">Suggested</span>}
              <div style={{ fontSize: 22, marginBottom: 4 }}>{MODE_ICONS[mode]}</div>
              <div style={{ fontWeight: 600 }}>{MODE_LABELS[mode]}</div>
              {!IMPLEMENTED_MODES.includes(mode) && <div className="text-muted" style={{ fontSize: 12 }}>Coming soon</div>}
              {IMPLEMENTED_MODES.includes(mode) && (
                <div className="text-muted" style={{ fontSize: 12 }}>
                  {CONFIGURABLE_MODES.includes(mode) ? "Configure & generate" : hasReady ? "Start learning" : "Generate"}
                </div>
              )}
              {busyMode === mode && (
                <div className="gen-progress">
                  {progress ? (
                    <>
                      <div className="progress-bar-track">
                        <div
                          className="progress-bar-fill"
                          style={{ width: `${Math.round((progress.current / progress.total) * 100)}%` }}
                        />
                      </div>
                      <div className="progress-bar-label">
                        {Math.round((progress.current / progress.total) * 100)}% · {PROGRESS_UNIT_LABELS[mode] ?? "step"}{" "}
                        {progress.current}/{progress.total}
                        {progress.etaSeconds !== null && progress.etaSeconds > 0
                          ? ` · ~${formatEta(progress.etaSeconds)} left`
                          : ""}
                      </div>
                    </>
                  ) : (
                    <div className="text-muted" style={{ fontSize: 12 }}>
                      Working...
                    </div>
                  )}
                </div>
              )}
            </button>
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

      {error && <p className="error-text">{error}</p>}
      </div>
      <TutorPanel chatId={chatId} />
    </div>
  );
}
