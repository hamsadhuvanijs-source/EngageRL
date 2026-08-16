"use client";

import { useRef } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { API_BASE } from "@/lib/api";
import type { VideoContent } from "@/types/api";

export function VideoView({ content }: { content: VideoContent }) {
  const { reportProgress } = useTelemetry();
  const lastReportedRef = useRef(0);

  // Real watched-fraction of actual playback time, not a proxy — throttled so scrubbing
  // doesn't spam an event per frame.
  const onTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement>) => {
    const video = e.currentTarget;
    if (!video.duration) return;
    const ratio = video.currentTime / video.duration;
    if (ratio - lastReportedRef.current >= 0.02 || ratio >= 0.99) {
      lastReportedRef.current = ratio;
      reportProgress(ratio);
    }
  };

  return (
    <>
      <h1>Video</h1>

      <video
        className="video-player"
        src={`${API_BASE}${content.video_url}`}
        controls
        onTimeUpdate={onTimeUpdate}
      />

      <div className="video-transcript">
        <h2>Transcript</h2>
        {content.scenes.map((scene, i) => (
          <p className="video-transcript-line" key={i}>
            <span className="video-transcript-index">{i + 1}</span>
            {scene.narration}
          </p>
        ))}
      </div>
    </>
  );
}
