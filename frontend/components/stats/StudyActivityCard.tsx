import type { StatsOut } from "@/types/api";

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function StudyActivityCard({ stats }: { stats: StatsOut }) {
  const tiles = [
    { label: "Chats", value: stats.chat_count },
    { label: "Sources", value: stats.source_count },
    { label: "Sessions", value: stats.session_count },
    { label: "Active time", value: formatDuration(stats.total_active_seconds) },
  ];

  return (
    <div className="stat-grid">
      {tiles.map((tile) => (
        <div className="stat-tile" key={tile.label}>
          <div className="stat-tile-value">{tile.value}</div>
          <div className="stat-tile-label">{tile.label}</div>
        </div>
      ))}
    </div>
  );
}
