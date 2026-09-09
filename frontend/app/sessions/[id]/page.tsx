"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ComicView } from "@/components/modes/ComicView";
import { FlashcardsView } from "@/components/modes/FlashcardsView";
import { FlowchartView } from "@/components/modes/FlowchartView";
import { PodcastView } from "@/components/modes/PodcastView";
import { QAView } from "@/components/modes/QAView";
import { QuizView } from "@/components/modes/QuizView";
import { SummaryView } from "@/components/modes/SummaryView";
import { VideoView } from "@/components/modes/VideoView";
import { ENJOYMENT_GIVEN_KEY, EnjoymentPrompt } from "@/components/session/EnjoymentPrompt";
import { StillEngagedPrompt } from "@/components/session/StillEngagedPrompt";
import { TelemetryProvider, useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { TutorPanel } from "@/components/tutor/TutorPanel";
import { ApiError, completeSession, getSession } from "@/lib/api";
import { loadContentState, saveContentState } from "@/lib/persistence";
import type {
  ComicContent,
  FlashcardsContent,
  FlowchartContent,
  PodcastContent,
  QAContent,
  QuizContent,
  SessionCompleteResponse,
  SessionDetailOut,
  SummaryContent,
  VideoContent,
} from "@/types/api";

// Below this fraction of real per-item progress (questions answered, cards seen, video
// watched, ...), marking a session "complete" is treated as leaving early rather than
// actually finishing — worth asking why before it counts as done.
const COMPLETION_WARN_THRESHOLD = 0.85;

const INCOMPLETE_REASONS: { key: string; label: string }[] = [
  { key: "too_hard", label: "Too hard to follow" },
  { key: "not_interesting", label: "Not that interesting" },
  { key: "ran_out_of_time", label: "Ran out of time" },
  { key: "moving_on", label: "Just want to move on" },
];

export default function SessionPage({ params }: { params: { id: string } }) {
  const sessionId = params.id;
  const [detail, setDetail] = useState<SessionDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSession(sessionId)
      .then(setDetail)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load session."));
  }, [sessionId]);

  if (error) return <p className="error-text page">{error}</p>;
  if (!detail) return <p className="page">Loading...</p>;

  return (
    <div className="session-layout">
      <div className="session-main">
        <Link href={`/chats/${detail.chat_id}`} className="back-link">
          ← Back to chat
        </Link>
        <TelemetryProvider sessionId={sessionId}>
          <SessionContent detail={detail} />
        </TelemetryProvider>
      </div>
      <TutorPanel chatId={detail.chat_id} />
    </div>
  );
}

type GateStage = "none" | "incomplete" | "enjoyment";

function SessionContent({ detail }: { detail: SessionDetailOut }) {
  const router = useRouter();
  const { flushNow, progressRatio, reportFeedback, reportIncompleteReason } = useTelemetry();
  const [result, setResult] = useState<SessionCompleteResponse | null>(null);
  const [completing, setCompleting] = useState(false);
  const [gateStage, setGateStage] = useState<GateStage>("none");

  const finishComplete = async () => {
    setGateStage("none");
    setCompleting(true);
    try {
      await flushNow();
      const res = await completeSession(detail.session.id);
      setResult(res);
    } finally {
      setCompleting(false);
    }
  };

  const proceedPastIncompleteCheck = () => {
    const alreadyGiven = loadContentState<boolean>(detail.session.id, ENJOYMENT_GIVEN_KEY) ?? false;
    if (!alreadyGiven) {
      setGateStage("enjoyment");
      return;
    }
    void finishComplete();
  };

  const onStartComplete = () => {
    if (progressRatio !== null && progressRatio < COMPLETION_WARN_THRESHOLD) {
      setGateStage("incomplete");
      return;
    }
    proceedPastIncompleteCheck();
  };

  const onChooseReason = async (reason: string) => {
    await reportIncompleteReason(reason, progressRatio ?? 0);
    proceedPastIncompleteCheck();
  };

  const onFinishAnywayNoReason = () => {
    proceedPastIncompleteCheck();
  };

  const onAnswerEnjoyment = async (enjoying: boolean) => {
    saveContentState(detail.session.id, ENJOYMENT_GIVEN_KEY, true);
    await reportFeedback(enjoying, "end");
    void finishComplete();
  };

  const onSkipEnjoyment = () => {
    void finishComplete();
  };

  if (result) {
    return (
      <>
        <h1>Session complete</h1>
        <p>Engagement score: {result.engagement_score.toFixed(2)}</p>
        <p className="text-muted">
          Updated bandit params for this mode: alpha={result.bandit_params.alpha.toFixed(2)}, beta=
          {result.bandit_params.beta.toFixed(2)}
        </p>
        <button className="btn" onClick={() => router.push(`/chats/${detail.chat_id}`)}>
          Back to chat
        </button>
      </>
    );
  }

  return (
    <>
      {detail.mode === "summary" && detail.content_json && (
        <SummaryView content={detail.content_json as SummaryContent} />
      )}
      {detail.mode === "quiz" && detail.content_json && (
        <QuizView content={detail.content_json as QuizContent} contentId={detail.session.generated_content_id} />
      )}
      {detail.mode === "flashcards" && detail.content_json && (
        <FlashcardsView
          content={detail.content_json as FlashcardsContent}
          contentId={detail.session.generated_content_id}
        />
      )}
      {detail.mode === "qa" && detail.content_json && (
        <QAView content={detail.content_json as QAContent} contentId={detail.session.generated_content_id} />
      )}
      {detail.mode === "comic" && detail.content_json && <ComicView content={detail.content_json as ComicContent} />}
      {detail.mode === "video" && detail.content_json && <VideoView content={detail.content_json as VideoContent} />}
      {detail.mode === "podcast" && detail.content_json && (
        <PodcastView content={detail.content_json as PodcastContent} />
      )}
      {detail.mode === "flowchart" && detail.content_json && (
        <FlowchartView content={detail.content_json as FlowchartContent} />
      )}

      <div style={{ marginTop: 32 }}>
        <button className="btn" onClick={onStartComplete} disabled={completing || gateStage !== "none"}>
          {completing ? "Finishing..." : "Mark as complete"}
        </button>
      </div>

      <StillEngagedPrompt
        sessionId={detail.session.id}
        chatId={detail.chat_id}
        currentMode={detail.mode}
        initialOverageThresholdSeconds={detail.overage_threshold_seconds}
      />

      <EnjoymentPrompt sessionId={detail.session.id} expectedSeconds={detail.expected_seconds} />

      {gateStage === "incomplete" && (
        <div className="still-engaged-overlay">
          <div className="still-engaged-modal">
            <div className="still-engaged-icon">🤔</div>
            <h3>Looks like you're not quite done</h3>
            <p className="text-muted">
              You&apos;ve gotten through about {Math.round((progressRatio ?? 0) * 100)}% of this. Mind telling us
              why you&apos;re wrapping up now? It helps us suggest better next time.
            </p>
            <div className="still-engaged-actions">
              {INCOMPLETE_REASONS.map((r) => (
                <button key={r.key} className="btn-secondary" onClick={() => onChooseReason(r.key)}>
                  {r.label}
                </button>
              ))}
              <button className="btn" onClick={onFinishAnywayNoReason}>
                Just finish
              </button>
            </div>
          </div>
        </div>
      )}

      {gateStage === "enjoyment" && (
        <div className="still-engaged-overlay">
          <div className="still-engaged-modal">
            <div className="still-engaged-icon">💭</div>
            <h3>One quick thing</h3>
            <p className="text-muted">Did you enjoy learning it this way?</p>
            <div className="still-engaged-actions">
              <button className="btn" onClick={() => onAnswerEnjoyment(true)}>
                🙂 Yes
              </button>
              <button className="btn" onClick={() => onAnswerEnjoyment(false)}>
                🙁 Not really
              </button>
              <button className="btn-secondary" onClick={onSkipEnjoyment}>
                Skip
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
