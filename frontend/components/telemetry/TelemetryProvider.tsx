"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { makeEvent } from "@/lib/telemetry/events";
import { TelemetryCollector } from "@/lib/telemetry/collector";
import type { TelemetryEventType } from "@/types/api";

const SCROLL_THROTTLE_MS = 1000;
const MOUSE_THROTTLE_MS = 2000;
const DWELL_TICK_MS = 5000;

interface TelemetryContextValue {
  flushNow: () => Promise<void>;
  // Cumulative active (tab-visible) dwell seconds for this session so far — lets UI like the
  // "still with it?" check-in compare live progress against the expected-time threshold
  // without waiting for a full telemetry round-trip.
  activeSeconds: number;
  // How far through the actual content the user has gotten (0-1), from real per-mode signals
  // (questions answered, cards seen, video seconds watched, ...). null means this mode doesn't
  // report discrete progress (e.g. summary) — callers should treat that as "no data" rather
  // than "0% done".
  progressRatio: number | null;
  // Mode view components call this as the user progresses; monotonic (never goes down) both
  // locally and server-side, so navigating back doesn't erase credit already earned. Also
  // queues a "progress" telemetry event carrying the same ratio for real, data-driven
  // completion scoring (see telemetry/scoring.py::_completion_ratio).
  reportProgress: (ratio: number) => void;
  // Explicit self-reported "are you enjoying this?" signal — real user feedback, not inferred
  // from behavior. Flushes immediately since it's a rare, deliberate action.
  reportFeedback: (enjoying: boolean, promptedAt: "mid" | "end") => Promise<void>;
  // Explicit reason for marking a session complete before actually finishing it.
  reportIncompleteReason: (reason: string, completionRatio: number) => Promise<void>;
  // Real per-question correctness for quiz mode — feeds the RL reward's accuracy component and
  // the learner state's quiz_accuracy_level feature (see backend app/rl/state.py, reward.py).
  reportQuizAnswer: (questionIndex: number, correct: boolean) => void;
}

const TelemetryContext = createContext<TelemetryContextValue | null>(null);

export function useTelemetry(): TelemetryContextValue {
  const ctx = useContext(TelemetryContext);
  if (!ctx) throw new Error("useTelemetry must be used within a TelemetryProvider");
  return ctx;
}

export function TelemetryProvider({ sessionId, children }: { sessionId: string; children: ReactNode }) {
  const collectorRef = useRef<TelemetryCollector | null>(null);
  // Lets flushNow() credit dwell time immediately (e.g. right before completing a
  // session) instead of only on the fixed 5s tick — see creditDwell below.
  const creditDwellRef = useRef<() => void>(() => {});
  const pushRef = useRef<(type: TelemetryEventType, payload?: Record<string, unknown>) => void>(() => {});
  const [activeSeconds, setActiveSeconds] = useState(0);
  const [progressRatio, setProgressRatio] = useState<number | null>(null);

  useEffect(() => {
    const collector = new TelemetryCollector(sessionId);
    collectorRef.current = collector;
    collector.start();

    const push = (type: TelemetryEventType, payload: Record<string, unknown> = {}) =>
      collector.push(makeEvent(type, payload));
    pushRef.current = push;

    const onVisibility = () => push("visibility_change", { visible: document.visibilityState === "visible" });
    document.addEventListener("visibilitychange", onVisibility);
    push("visibility_change", { visible: document.visibilityState === "visible" });

    let lastScroll = 0;
    const onScroll = () => {
      const now = Date.now();
      if (now - lastScroll < SCROLL_THROTTLE_MS) return;
      lastScroll = now;
      push("scroll", { scrollY: window.scrollY });
    };
    window.addEventListener("scroll", onScroll, { passive: true });

    const onKeydown = () => push("keypress", {});
    window.addEventListener("keydown", onKeydown);

    let lastMouse = 0;
    const onMouseMove = () => {
      const now = Date.now();
      if (now - lastMouse < MOUSE_THROTTLE_MS) return;
      lastMouse = now;
      push("mouse_move", {});
    };
    window.addEventListener("mousemove", onMouseMove);

    // Clicking is the primary way users interact with quiz/flashcards/Q&A — without
    // this, answering questions or flipping cards generated zero interaction signal.
    const onClick = () => push("click", {});
    window.addEventListener("click", onClick);

    // Credits elapsed visible time since the last credit, then resets the clock.
    // Called both on the fixed tick AND from flushNow(), so a session that completes
    // well before the next tick (the common case — most study sessions are short)
    // still gets accurate dwell credit instead of a hard zero.
    let lastCreditAt = Date.now();
    const creditDwell = () => {
      if (document.visibilityState !== "visible") {
        lastCreditAt = Date.now();
        return;
      }
      const seconds = (Date.now() - lastCreditAt) / 1000;
      if (seconds > 0.1) {
        push("dwell", { seconds });
        setActiveSeconds((prev) => prev + seconds);
      }
      lastCreditAt = Date.now();
    };
    creditDwellRef.current = creditDwell;

    const dwellInterval = setInterval(creditDwell, DWELL_TICK_MS);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("keydown", onKeydown);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("click", onClick);
      clearInterval(dwellInterval);
      creditDwell();
      collector.stop();
      collectorRef.current = null;
      creditDwellRef.current = () => {};
      pushRef.current = () => {};
    };
  }, [sessionId]);

  const flushNow = async () => {
    creditDwellRef.current();
    await collectorRef.current?.flushNow();
  };

  const reportProgress = (ratio: number) => {
    const clamped = Math.max(0, Math.min(1, ratio));
    setProgressRatio((prev) => (prev === null ? clamped : Math.max(prev, clamped)));
    pushRef.current("progress", { ratio: clamped });
  };

  const reportFeedback = async (enjoying: boolean, promptedAt: "mid" | "end") => {
    pushRef.current("enjoyment_feedback", { enjoying, prompted_at: promptedAt });
    await flushNow();
  };

  const reportIncompleteReason = async (reason: string, completionRatio: number) => {
    pushRef.current("incomplete_reason", { reason, completion_ratio: completionRatio });
    await flushNow();
  };

  const reportQuizAnswer = (questionIndex: number, correct: boolean) => {
    pushRef.current("quiz_answer", { question_index: questionIndex, correct });
  };

  return (
    <TelemetryContext.Provider
      value={{
        flushNow,
        activeSeconds,
        progressRatio,
        reportProgress,
        reportFeedback,
        reportIncompleteReason,
        reportQuizAnswer,
      }}
    >
      {children}
    </TelemetryContext.Provider>
  );
}
