"use client";

import { useEffect, useRef, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type { FlashcardsContent } from "@/types/api";

const STATE_KEY = "index";
const REVEALED_STATE_KEY = "revealed";

export function FlashcardsView({ content, contentId }: { content: FlashcardsContent; contentId: string }) {
  const { flushNow, reportProgress } = useTelemetry();
  const [index, setIndex] = useState(() => {
    const saved = loadContentState<number>(contentId, STATE_KEY) ?? 0;
    return saved < content.cards.length ? saved : 0;
  });
  const [flipped, setFlipped] = useState(false);
  // Progress is "cards actually flipped to see the answer", not "cards navigated past" — a
  // flashcard you never turn over is a flashcard you didn't use. Clicking Next without flipping
  // earns no progress. Persisted so a resumed session keeps its earned credit.
  const revealedRef = useRef<Set<number>>(new Set(loadContentState<number[]>(contentId, REVEALED_STATE_KEY) ?? []));

  const card = content.cards[index];
  const isLast = index === content.cards.length - 1;
  const isFirst = index === 0;

  const reportRevealProgress = () => {
    reportProgress(revealedRef.current.size / content.cards.length);
  };

  // Re-emit already-earned progress on (re)mount so a resumed session doesn't look like it
  // regressed to 0%.
  useEffect(() => {
    reportRevealProgress();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const goTo = (next: number) => {
    setIndex(next);
    setFlipped(false);
    saveContentState(contentId, STATE_KEY, next);
    void flushNow();
  };

  const onFlip = () => {
    setFlipped((f) => {
      const nowFlipped = !f;
      // Count the card the first time its answer is shown.
      if (nowFlipped && !revealedRef.current.has(index)) {
        revealedRef.current.add(index);
        saveContentState(contentId, REVEALED_STATE_KEY, [...revealedRef.current]);
        reportRevealProgress();
      }
      return nowFlipped;
    });
    void flushNow();
  };

  if (!card) return <p>No flashcards were generated.</p>;

  return (
    <>
      <h1>Flashcards</h1>
      <p className="text-muted" style={{ fontSize: 13 }}>
        Card {index + 1} of {content.cards.length}
      </p>

      <button className="flashcard" onClick={onFlip}>
        <div className="flashcard-label">{flipped ? "Answer" : "Question"}</div>
        <div className="flashcard-text">{flipped ? card.answer : card.question}</div>
        <div className="flashcard-hint">Click to {flipped ? "see question" : "reveal answer"}</div>
      </button>

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button className="btn btn-secondary" onClick={() => goTo(index - 1)} disabled={isFirst}>
          Previous
        </button>
        <button className="btn" onClick={() => goTo(index + 1)} disabled={isLast}>
          Next
        </button>
      </div>
    </>
  );
}
