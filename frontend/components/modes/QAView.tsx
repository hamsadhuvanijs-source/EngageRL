"use client";

import { useEffect, useRef, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type { QAContent } from "@/types/api";

const STATE_KEY = "openIndices";
const REVEALED_STATE_KEY = "revealed";

export function QAView({ content, contentId }: { content: QAContent; contentId: string }) {
  const { flushNow, reportProgress } = useTelemetry();
  const [openIndices, setOpenIndices] = useState<number[]>(
    () => loadContentState<number[]>(contentId, STATE_KEY) ?? []
  );
  // Progress is "answers ever revealed", monotonic — collapsing an item back doesn't take the
  // credit away, but nor does re-collapsing everything drop you to 0%.
  const revealedRef = useRef<Set<number>>(
    new Set(loadContentState<number[]>(contentId, REVEALED_STATE_KEY) ?? loadContentState<number[]>(contentId, STATE_KEY) ?? [])
  );

  const reportRevealProgress = () => {
    reportProgress(revealedRef.current.size / content.items.length);
  };

  useEffect(() => {
    reportRevealProgress();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onToggle = (i: number) => {
    setOpenIndices((prev) => {
      const next = prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i];
      saveContentState(contentId, STATE_KEY, next);
      return next;
    });
    if (!revealedRef.current.has(i)) {
      revealedRef.current.add(i);
      saveContentState(contentId, REVEALED_STATE_KEY, [...revealedRef.current]);
      reportRevealProgress();
    }
    void flushNow();
  };

  return (
    <>
      <h1>Q&amp;A</h1>
      {content.items.map((item, i) => (
        <div className="quiz-question" key={i}>
          <button className="qa-toggle" onClick={() => onToggle(i)}>
            <strong>
              {i + 1}. {item.question}
            </strong>
          </button>
          {openIndices.includes(i) && <p className="text-muted" style={{ marginTop: 8 }}>{item.answer}</p>}
        </div>
      ))}
    </>
  );
}
