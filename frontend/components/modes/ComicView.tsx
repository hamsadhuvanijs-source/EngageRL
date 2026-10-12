"use client";

import { useEffect, useRef } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import { API_BASE } from "@/lib/api";
import type { ComicContent } from "@/types/api";

export function ComicView({ content }: { content: ComicContent }) {
  const { reportProgress } = useTelemetry();
  const panelRefs = useRef<(HTMLDivElement | null)[]>([]);
  const maxSeenRef = useRef(-1);

  // Progress is "furthest panel actually scrolled into view", tracked via IntersectionObserver
  // rather than assumed from scroll position alone (panel sizes vary with art/dialogue length).
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const index = panelRefs.current.indexOf(entry.target as HTMLDivElement);
          if (index > maxSeenRef.current) {
            maxSeenRef.current = index;
            reportProgress((index + 1) / content.panels.length);
          }
        }
      },
      { threshold: 0.5 }
    );
    panelRefs.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <>
      <h1>Comic</h1>

      {content.image_error && (
        <div className="comic-error-banner">
          Artwork couldn&apos;t be generated for this comic (likely an API quota/billing limit on the image
          model) — the story below is still complete, just without pictures.
        </div>
      )}

      <div className="comic-strip">
        {content.panels.map((panel, i) => (
          <div
            className="comic-panel"
            key={i}
            ref={(el) => {
              panelRefs.current[i] = el;
            }}
          >
            <div className="comic-panel-image-wrap">
              {panel.image_url ? (
                <img className="comic-panel-image" src={`${API_BASE}${panel.image_url}`} alt={panel.scene_description} />
              ) : (
                <div className="comic-panel-placeholder">Artwork unavailable</div>
              )}
              {panel.caption && <div className="comic-caption">{panel.caption}</div>}
              <div className="comic-panel-number">{i + 1}</div>
            </div>

            <div className="comic-script">
              {panel.dialogue.map((line, li) => (
                <div className={`comic-bubble ${li % 2 === 0 ? "comic-bubble-left" : "comic-bubble-right"}`} key={li}>
                  <span className="comic-speaker">{line.speaker}</span>
                  {line.text}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
