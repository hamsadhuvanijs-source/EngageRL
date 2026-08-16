import { API_BASE, postEvents } from "@/lib/api";
import type { TelemetryEvent } from "@/types/api";

const FLUSH_INTERVAL_MS = 5000;

export class TelemetryCollector {
  private buffer: TelemetryEvent[] = [];
  private intervalId: ReturnType<typeof setInterval> | null = null;

  constructor(private sessionId: string) {}

  push(event: TelemetryEvent) {
    this.buffer.push(event);
  }

  start() {
    this.intervalId = setInterval(() => {
      void this.flushNow();
    }, FLUSH_INTERVAL_MS);
  }

  stop() {
    if (this.intervalId !== null) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
    this.flushSync();
  }

  /** Public: flush the buffer over a normal fetch. Safe to await before completing a session. */
  async flushNow() {
    if (this.buffer.length === 0) return;
    const events = this.buffer.splice(0, this.buffer.length);
    try {
      await postEvents(this.sessionId, events);
    } catch {
      // best-effort telemetry: drop on failure rather than blocking the learning UI
    }
  }

  /** Used on unmount/unload where an async fetch may be cancelled by the browser. */
  private flushSync() {
    if (this.buffer.length === 0) return;
    const events = this.buffer.splice(0, this.buffer.length);
    if (typeof navigator !== "undefined" && navigator.sendBeacon) {
      const blob = new Blob([JSON.stringify({ events })], { type: "application/json" });
      navigator.sendBeacon(`${API_BASE}/sessions/${this.sessionId}/events`, blob);
    } else {
      void postEvents(this.sessionId, events).catch(() => {});
    }
  }
}
