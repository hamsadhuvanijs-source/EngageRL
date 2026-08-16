import type { Mode, ModePreference } from "@/types/api";

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

const MODE_ORDER: Mode[] = ["summary", "quiz", "flashcards", "qa", "flowchart", "podcast", "comic", "video"];

export function ModePreferenceBars({ preference }: { preference: Record<Mode, ModePreference> }) {
  return (
    <div>
      {MODE_ORDER.map((mode) => {
        const pref = preference[mode];
        const pct = Math.round((pref?.mean ?? 0.5) * 100);
        return (
          <div className="mode-pref-row" key={mode}>
            <span className="mode-pref-label">{MODE_LABELS[mode]}</span>
            <div className="mode-pref-track">
              <div className="mode-pref-fill" style={{ width: `${pct}%` }} />
            </div>
            <span className="mode-pref-value">{pct}%</span>
          </div>
        );
      })}
    </div>
  );
}
