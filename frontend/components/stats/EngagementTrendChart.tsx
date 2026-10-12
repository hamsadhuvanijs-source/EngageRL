"use client";

import { useMemo, useState } from "react";

import type { EngagementPoint } from "@/types/api";

const WIDTH = 640;
const HEIGHT = 220;
const PAD_LEFT = 36;
const PAD_RIGHT = 16;
const PAD_TOP = 16;
const PAD_BOTTOM = 28;
const MAX_POINTS = 20;
const ACCENT = "var(--accent)";
const GRID_COLOR = "var(--border)";
const AXIS_TEXT_COLOR = "var(--text-faint)";

export function EngagementTrendChart({ points }: { points: EngagementPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const recent = points.slice(-MAX_POINTS);

  const plotWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;

  const coords = useMemo(
    () =>
      recent.map((p, i) => {
        const x = recent.length === 1 ? PAD_LEFT + plotWidth / 2 : PAD_LEFT + (i / (recent.length - 1)) * plotWidth;
        const y = PAD_TOP + (1 - p.engagement_score) * plotHeight;
        return { x, y, point: p };
      }),
    [recent, plotWidth, plotHeight]
  );

  if (recent.length === 0) {
    return <p className="text-muted">No completed study sessions yet — your engagement trend will show up here.</p>;
  }

  const linePath = coords.map((c, i) => `${i === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" ");
  const gridLines = [0, 0.25, 0.5, 0.75, 1];

  const hovered = hoverIndex !== null ? coords[hoverIndex] : null;

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const relX = ((e.clientX - rect.left) / rect.width) * WIDTH;
    let nearest = 0;
    let nearestDist = Infinity;
    coords.forEach((c, i) => {
      const dist = Math.abs(c.x - relX);
      if (dist < nearestDist) {
        nearestDist = dist;
        nearest = i;
      }
    });
    setHoverIndex(nearest);
  };

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {gridLines.map((g) => {
          const y = PAD_TOP + (1 - g) * plotHeight;
          return (
            <g key={g}>
              <line x1={PAD_LEFT} y1={y} x2={WIDTH - PAD_RIGHT} y2={y} stroke={GRID_COLOR} strokeWidth={1} />
              <text x={PAD_LEFT - 8} y={y + 4} textAnchor="end" fontSize={11} fill={AXIS_TEXT_COLOR}>
                {g.toFixed(2)}
              </text>
            </g>
          );
        })}

        <path d={linePath} fill="none" stroke={ACCENT} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />

        {coords.map((c, i) => (
          <circle
            key={i}
            cx={c.x}
            cy={c.y}
            r={i === coords.length - 1 ? 4 : 3}
            fill={ACCENT}
            stroke="var(--bg)"
            strokeWidth={1.5}
          />
        ))}

        {hovered && (
          <>
            <line
              x1={hovered.x}
              y1={PAD_TOP}
              x2={hovered.x}
              y2={HEIGHT - PAD_BOTTOM}
              stroke={GRID_COLOR}
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <circle cx={hovered.x} cy={hovered.y} r={5} fill="none" stroke={ACCENT} strokeWidth={2} />
          </>
        )}

        <rect
          x={PAD_LEFT}
          y={PAD_TOP}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHoverIndex(null)}
        />
      </svg>

      {hovered && (
        <div
          style={{
            position: "absolute",
            left: `${(hovered.x / WIDTH) * 100}%`,
            top: 0,
            transform: "translate(-50%, -100%)",
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
            borderRadius: 6,
            padding: "4px 8px",
            fontSize: 12,
            whiteSpace: "nowrap",
            pointerEvents: "none",
            color: "var(--text)",
          }}
        >
          {new Date(hovered.point.completed_at).toLocaleDateString()} — {hovered.point.engagement_score.toFixed(2)}
        </div>
      )}
    </div>
  );
}
