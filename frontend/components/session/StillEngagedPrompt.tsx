"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { postStillEngaged, suggestMode } from "@/lib/api";
import type { Mode, SuggestModeOut } from "@/types/api";

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

const SNOOZE_SECONDS = 120;
const NUM_ALTERNATIVES = 2;

type Stage = "hidden" | "asking" | "suggesting";

export function StillEngagedPrompt({
  sessionId,
  chatId,
  currentMode,
  initialOverageThresholdSeconds,
}: {
  sessionId: string;
  chatId: string;
  currentMode: Mode;
  initialOverageThresholdSeconds: number;
}) {
  const router = useRouter();
  const { activeSeconds } = useTelemetry();
  const [threshold, setThreshold] = useState(initialOverageThresholdSeconds);
  const [snoozedUntil, setSnoozedUntil] = useState<number | null>(null);
  const [stage, setStage] = useState<Stage>("hidden");
  const [suggestion, setSuggestion] = useState<SuggestModeOut | null>(null);
  const [busy, setBusy] = useState(false);

  // Fires once active (tab-visible) dwell time crosses the personalized overage threshold —
  // the same cliff the engagement scorer uses server-side, so this pops right when a session
  // would otherwise start reading as "disengaged."
  useEffect(() => {
    if (stage !== "hidden") return;
    if (snoozedUntil !== null && activeSeconds < snoozedUntil) return;
    if (activeSeconds >= threshold) setStage("asking");
  }, [activeSeconds, threshold, snoozedUntil, stage]);

  const onStillReading = async () => {
    setBusy(true);
    try {
      const res = await postStillEngaged(sessionId, true);
      setThreshold(res.overage_threshold_seconds);
      setSnoozedUntil(null);
    } catch {
      setSnoozedUntil(activeSeconds + SNOOZE_SECONDS);
    } finally {
      setStage("hidden");
      setBusy(false);
    }
  };

  const onSuggestSomethingElse = async () => {
    setBusy(true);
    try {
      await postStillEngaged(sessionId, false).catch(() => {});
      const s = await suggestMode(chatId);
      setSuggestion(s);
      setStage("suggesting");
    } catch {
      setSnoozedUntil(activeSeconds + SNOOZE_SECONDS);
      setStage("hidden");
    } finally {
      setBusy(false);
    }
  };

  const onKeepGoingAnyway = async () => {
    setBusy(true);
    try {
      const res = await postStillEngaged(sessionId, true);
      setThreshold(res.overage_threshold_seconds);
    } finally {
      setStage("hidden");
      setBusy(false);
    }
  };

  const onDismiss = () => {
    setSnoozedUntil(activeSeconds + SNOOZE_SECONDS);
    setStage("hidden");
  };

  const onPickOwn = () => {
    router.push(`/chats/${chatId}`);
  };

  if (stage === "hidden") return null;

  // Top modes by the bandit's real posterior mean (accumulated from actual past session
  // scores — not a fresh random draw), excluding whatever mode the user is already in.
  const alternatives = suggestion
    ? (Object.entries(suggestion.action_scores) as [Mode, number][])
        .filter(([mode]) => mode !== currentMode)
        .sort((a, b) => b[1] - a[1])
        .slice(0, NUM_ALTERNATIVES)
    : [];

  return (
    <div className="still-engaged-overlay">
      <div className="still-engaged-modal">
        <button className="still-engaged-close" onClick={onDismiss} aria-label="Dismiss">
          ×
        </button>

        {stage === "asking" && (
          <>
            <div className="still-engaged-icon">👋</div>
            <h3>Still with it?</h3>
            <p className="text-muted">
              You&apos;ve been on this a while — just checking in. Want to keep going, or should I suggest
              something that might click better?
            </p>
            <div className="still-engaged-actions">
              <button className="btn" onClick={onStillReading} disabled={busy}>
                Yeah, I&apos;m still reading
              </button>
              <button className="btn-secondary" onClick={onSuggestSomethingElse} disabled={busy}>
                Suggest something else
              </button>
            </div>
          </>
        )}

        {stage === "suggesting" && alternatives.length > 0 && (
          <>
            <div className="still-engaged-icon">💡</div>
            <h3>Try something else?</h3>
            <p className="text-muted">
              Based on how you&apos;ve engaged with things before, these tend to work better for you than{" "}
              {MODE_LABELS[currentMode]}:
            </p>
            <div className="still-engaged-actions">
              {alternatives.map(([mode]) => (
                <button
                  key={mode}
                  className="btn"
                  onClick={() => router.push(`/chats/${chatId}?mode=${mode}`)}
                  disabled={busy}
                >
                  Switch to {MODE_LABELS[mode]}
                </button>
              ))}
              <button className="btn-secondary" onClick={onPickOwn} disabled={busy}>
                Let me pick something else
              </button>
              <button className="btn-secondary" onClick={onKeepGoingAnyway} disabled={busy}>
                No, keep going
              </button>
            </div>
          </>
        )}

        {stage === "suggesting" && alternatives.length === 0 && (
          <>
            <div className="still-engaged-icon">🤔</div>
            <h3>This still looks like a good fit</h3>
            <p className="text-muted">
              Based on your activity, {MODE_LABELS[currentMode]} is actually still your best bet right now — no
              better suggestion to offer.
            </p>
            <div className="still-engaged-actions">
              <button className="btn" onClick={onKeepGoingAnyway} disabled={busy}>
                Keep going
              </button>
              <button className="btn-secondary" onClick={onPickOwn} disabled={busy}>
                Let me pick something else anyway
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
