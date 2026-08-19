"use client";

import { useEffect, useState } from "react";

import { EngagementTrendChart } from "@/components/stats/EngagementTrendChart";
import { ModePreferenceBars } from "@/components/stats/ModePreferenceBars";
import { RecentChatsList } from "@/components/stats/RecentChatsList";
import { StudyActivityCard } from "@/components/stats/StudyActivityCard";
import { ApiError, getStats } from "@/lib/api";
import type { StatsOut } from "@/types/api";

export function StatsDashboard() {
  const [stats, setStats] = useState<StatsOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Failed to load stats."));
  }, []);

  if (error) return <p className="error-text">{error}</p>;
  if (!stats) return <p>Loading...</p>;

  return (
    <div>
      <h1>Your study activity</h1>

      <div className="dashboard-section">
        <StudyActivityCard stats={stats} />
      </div>

      <div className="dashboard-section">
        <h2>Engagement trend</h2>
        <EngagementTrendChart points={stats.engagement_trend} />
      </div>

      <div className="dashboard-section">
        <h2>Learning style preference</h2>
        <p className="text-muted" style={{ fontSize: 13, marginTop: -8, marginBottom: 16 }}>
          {stats.rl_policy.active_policy === "q_learning"
            ? `Learned from ${stats.rl_policy.completed_sessions} completed sessions — how well each format tends to work for you, given how you're doing right now.`
            : `Still exploring (${stats.rl_policy.completed_sessions}/${stats.rl_policy.cold_start_threshold} sessions) — these will sharpen up as you complete a few more.`}
        </p>
        <ModePreferenceBars preference={stats.mode_preference} />
      </div>

      <div className="dashboard-section">
        <h2>Recent chats</h2>
        <RecentChatsList chats={stats.recent_chats} />
      </div>
    </div>
  );
}
