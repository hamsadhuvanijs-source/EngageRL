"use client";

import { useEffect, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type { QAContent } from "@/types/api";

const STATE_KEY = "openIndices";

export function QAView({ content, contentId }: { content: QAContent; contentId: string }) {
  const { flushNow, reportProgress } = useTelemetry();
  const [openIndices, setOpenIndices] = useState<number[]>(
    () => loadContentState<number[]>(contentId, STATE_KEY) ?? []
  );

  useEffect(() => {
    reportProgress(openIndices.length / content.items.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onToggle = (i: number) => {
    setOpenIndices((prev) => {
      const next = prev.includes(i) ? prev.filter((x) => x !== i) : [...prev, i];
      saveContentState(contentId, STATE_KEY, next);
      reportProgress(next.length / content.items.length);
      return next;
    });
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
