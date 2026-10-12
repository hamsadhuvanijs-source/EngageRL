"use client";

import { useEffect, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { loadContentState, saveContentState } from "@/lib/persistence";

export const ENJOYMENT_GIVEN_KEY = "enjoymentFeedbackGiven";
const MID_SESSION_FRACTION = 0.5;

/** Small, non-blocking mid-session check-in — real self-reported engagement data, not
 * inferred from behavior. Fires once, at the halfway point of the expected time for this
 * content, and only if the user hasn't already answered (mid or end) this session. */
export function EnjoymentPrompt({ sessionId, expectedSeconds }: { sessionId: string; expectedSeconds: number }) {
  const { activeSeconds, reportFeedback } = useTelemetry();
  const [given, setGiven] = useState(() => loadContentState<boolean>(sessionId, ENJOYMENT_GIVEN_KEY) ?? false);
  const [visible, setVisible] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (given || dismissed || visible) return;
    if (activeSeconds >= expectedSeconds * MID_SESSION_FRACTION) setVisible(true);
  }, [activeSeconds, expectedSeconds, given, dismissed, visible]);

  const answer = async (enjoying: boolean) => {
    setVisible(false);
    setGiven(true);
    saveContentState(sessionId, ENJOYMENT_GIVEN_KEY, true);
    await reportFeedback(enjoying, "mid");
  };

  if (!visible) return null;

  return (
    <div className="enjoyment-toast">
      <span>Enjoying this way of learning so far?</span>
      <div className="enjoyment-toast-actions">
        <button className="btn-secondary" onClick={() => answer(true)}>
          🙂 Yes
        </button>
        <button className="btn-secondary" onClick={() => answer(false)}>
          🙁 Not really
        </button>
        <button className="enjoyment-toast-dismiss" onClick={() => setDismissed(true)} aria-label="Dismiss">
          ×
        </button>
      </div>
    </div>
  );
}
