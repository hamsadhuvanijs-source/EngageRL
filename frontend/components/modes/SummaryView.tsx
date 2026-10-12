import type { SummaryContent } from "@/types/api";

export function SummaryView({ content }: { content: SummaryContent }) {
  return (
    <>
      <h1>Summary</h1>
      <div className="summary-block">{content.summary}</div>
    </>
  );
}
