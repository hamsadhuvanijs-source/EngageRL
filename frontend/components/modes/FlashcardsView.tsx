"use client";

import { useEffect, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type { FlashcardsContent } from "@/types/api";

const STATE_KEY = "index";
const MAX_INDEX_STATE_KEY = "maxIndex";

export function FlashcardsView({ content, contentId }: { content: FlashcardsContent; contentId: string }) {
  const { flushNow, reportProgress } = useTelemetry();
  const [index, setIndex] = useState(() => {
    const saved = loadContentState<number>(contentId, STATE_KEY) ?? 0;
    return saved < content.cards.length ? saved : 0;
  });
  const [flipped, setFlipped] = useState(false);

  const card = content.cards[index];
  const isLast = index === content.cards.length - 1;
  const isFirst = index === 0;

  // Progress is "furthest card actually reached", not "current card" — going back to review
  // an earlier card shouldn't erase credit for cards already seen.
  useEffect(() => {
    const maxSeen = Math.max(loadContentState<number>(contentId, MAX_INDEX_STATE_KEY) ?? 0, index);
    saveContentState(contentId, MAX_INDEX_STATE_KEY, maxSeen);
    reportProgress((maxSeen + 1) / content.cards.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index]);

  const goTo = (next: number) => {
    setIndex(next);
    setFlipped(false);
    saveContentState(contentId, STATE_KEY, next);
    void flushNow();
  };

  const onFlip = () => {
    setFlipped((f) => !f);
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
