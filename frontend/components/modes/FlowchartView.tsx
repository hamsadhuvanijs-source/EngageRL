"use client";

import { useEffect, useRef, useState } from "react";

import type { FlowchartContent } from "@/types/api";

// mermaid pulls in d3 and touches the DOM at import time, so it can't be a top-level import in a
// component Next.js still tries to server-render — it's dynamically imported inside the effect
// below, browser-side only, and the promise is memoized so a second flowchart session doesn't
// re-initialize it.
type MermaidApi = {
  initialize: (config: Record<string, unknown>) => void;
  render: (id: string, text: string) => Promise<{ svg: string }>;
};

// Vivid, evenly-spaced hues over the app's dark surface — used as solid node fills for mindmap
// sections (mermaid keys them off cScale0..N), with near-black labels for contrast, plus the
// same hue for that section's connector line.
const SECTION_HUES = ["#8b7bff", "#22d3ee", "#34d399", "#fbbf24", "#fb7185", "#38bdf8", "#e879f9", "#a3e635"];
const NODE_LABEL_INK = "#0b0d12";

let mermaidPromise: Promise<MermaidApi> | null = null;
function loadMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((mod) => {
      const mermaid = mod.default as unknown as MermaidApi;
      const themeVariables: Record<string, string> = {
        fontSize: "15px",
        primaryColor: "#1e2130",
        primaryTextColor: "#f2f3f8",
        primaryBorderColor: "#8b7bff",
        lineColor: "#8b8fa3",
        secondaryColor: "#242739",
        tertiaryColor: "#1e2130",
        // mindmap: root circle fill + label
        git0: SECTION_HUES[0],
        gitBranchLabel0: NODE_LABEL_INK,
      };
      SECTION_HUES.forEach((hue, i) => {
        themeVariables[`cScale${i}`] = hue; // section node fill
        themeVariables[`cScaleInv${i}`] = hue; // section connector line
        themeVariables[`cScaleLabel${i}`] = NODE_LABEL_INK; // section node label
      });

      mermaid.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "dark",
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        themeVariables,
        // Polish mermaid's generated CSS can't express through theme vars alone.
        themeCSS: `
          .mindmap-node rect, .mindmap-node circle, .mindmap-node polygon { rx: 10px; ry: 10px; }
          .mindmap-node text, .mindmap-node span, .mindmap-node .node-label { font-weight: 600; }
          .mindmap-node.section-root text, .section-root .text-inner-tspan { font-weight: 700; }
          .edge { stroke-width: 2.5px; opacity: 0.85; }
          .flowchart .node rect, .flowchart .node polygon { rx: 8px; ry: 8px; }
          .flowchart .edgePath .path { stroke-width: 1.75px; }
        `,
        flowchart: { curve: "basis", padding: 14, htmlLabels: false, nodeSpacing: 55, rankSpacing: 60 },
        mindmap: { padding: 14, maxNodeWidth: 190 },
      });
      return mermaid;
    });
  }
  return mermaidPromise;
}

const MIN_SCALE = 0.3;
const MAX_SCALE = 4;
// Per-notch factor for the +/- buttons.
const BUTTON_ZOOM_STEP = 1.35;
// Wheel/pinch: zoom factor is exp(-deltaY * K), so it tracks gesture magnitude instead of
// multiplying by a fixed step per event (which made a light trackpad pinch rocket the zoom).
const WHEEL_ZOOM_K = 0.0018;
const WHEEL_ZOOM_MIN_FACTOR = 0.5;
const WHEEL_ZOOM_MAX_FACTOR = 2;

type View = { scale: number; x: number; y: number };
const INITIAL_VIEW: View = { scale: 1, x: 0, y: 0 };
const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

// Scale by `ratio` about a point `(qx, qy)` measured from the viewport centre, keeping whatever
// is under that point fixed on screen (canvas transform-origin is centre).
function zoomedView(v: View, ratio: number, qx: number, qy: number): View {
  const scale = clamp(v.scale * ratio, MIN_SCALE, MAX_SCALE);
  const applied = scale / v.scale;
  return { scale, x: qx - (qx - v.x) * applied, y: qy - (qy - v.y) * applied };
}

// A flowchart / mindmap has no natural "how far through it are you" signal, so (like
// SummaryView) this mode reports no progress telemetry — its session is scored on dwell time
// plus whether the learner marked it complete.
export function FlowchartView({ content }: { content: FlowchartContent }) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const svgHostRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<{ startX: number; startY: number; originX: number; originY: number } | null>(null);

  const [renderError, setRenderError] = useState<string | null>(null);
  const [rendered, setRendered] = useState(false);
  const [view, setView] = useState<View>(INITIAL_VIEW);

  const isMindmap = content.diagram_type === "mindmap";

  useEffect(() => {
    let cancelled = false;

    loadMermaid()
      .then((mermaid) => mermaid.render(`mmd-${Math.random().toString(36).slice(2)}`, content.mermaid))
      .then(({ svg }) => {
        const host = svgHostRef.current;
        if (cancelled || !host) return;
        host.innerHTML = svg;
        const svgEl = host.querySelector("svg");
        if (svgEl) {
          svgEl.removeAttribute("width");
          svgEl.removeAttribute("height");
          svgEl.style.maxWidth = "none";
          svgEl.style.width = "100%";
          svgEl.style.height = "100%";
        }
        setRendered(true);
      })
      .catch((err: unknown) => {
        if (!cancelled) setRenderError(err instanceof Error ? err.message : "Could not render this diagram.");
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Non-passive wheel listener so preventDefault() actually stops the browser from page-zooming
  // on a trackpad pinch (which arrives as ctrl+wheel).
  useEffect(() => {
    const vp = viewportRef.current;
    if (!vp) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = vp.getBoundingClientRect();
      const qx = e.clientX - rect.left - rect.width / 2;
      const qy = e.clientY - rect.top - rect.height / 2;
      const factor = clamp(Math.exp(-e.deltaY * WHEEL_ZOOM_K), WHEEL_ZOOM_MIN_FACTOR, WHEEL_ZOOM_MAX_FACTOR);
      setView((v) => zoomedView(v, factor, qx, qy));
    };
    vp.addEventListener("wheel", onWheel, { passive: false });
    return () => vp.removeEventListener("wheel", onWheel);
  }, []);

  const zoomButton = (ratio: number) => setView((v) => zoomedView(v, ratio, 0, 0));
  const resetView = () => setView(INITIAL_VIEW);

  const onPointerDown = (e: React.PointerEvent) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startX: e.clientX, startY: e.clientY, originX: view.x, originY: view.y };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    setView((v) => ({ ...v, x: drag.originX + (e.clientX - drag.startX), y: drag.originY + (e.clientY - drag.startY) }));
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    dragRef.current = null;
  };

  return (
    <>
      <h1>🗺️ {content.title || "Flowchart"}</h1>

      {renderError ? (
        <div className="comic-error-banner">
          This diagram couldn&apos;t be rendered ({renderError}). The raw diagram source is below.
        </div>
      ) : (
        <p className="text-muted" style={{ fontSize: 13, marginTop: -4 }}>
          {isMindmap ? "Mindmap" : "Flowchart"} · drag to pan, scroll to zoom
        </p>
      )}

      {!renderError && (
        <div className="flowchart-frame">
          <div
            className="flowchart-viewport"
            ref={viewportRef}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
          >
            <div className="flowchart-canvas" style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}>
              <div className="flowchart-svg-host" ref={svgHostRef} />
            </div>
            {!rendered && <div className="flowchart-loading">Rendering diagram…</div>}
          </div>

          <div className="flowchart-controls">
            <button className="btn-icon" onClick={() => zoomButton(BUTTON_ZOOM_STEP)} title="Zoom in" aria-label="Zoom in">
              +
            </button>
            <button
              className="btn-icon"
              onClick={() => zoomButton(1 / BUTTON_ZOOM_STEP)}
              title="Zoom out"
              aria-label="Zoom out"
            >
              −
            </button>
            <button className="btn-icon" onClick={resetView} title="Reset view" aria-label="Reset view">
              ⤢
            </button>
          </div>
        </div>
      )}

      <details className="podcast-transcript-toggle" style={{ marginTop: 16 }} open={!!renderError}>
        <summary>Show diagram source</summary>
        <pre className="flowchart-source">{content.mermaid}</pre>
      </details>
    </>
  );
}
