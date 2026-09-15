import { API_BASE, authHeaders, postEvents } from "@/lib/api";
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

  /** Used on unmount/unload. `keepalive` lets the request outlive the page (like sendBeacon)
   * while still carrying the Authorization header the endpoint now requires — sendBeacon
   * can't set headers. Telemetry batches are far under keepalive's 64KB body limit. */
  private flushSync() {
    if (this.buffer.length === 0) return;
    const events = this.buffer.splice(0, this.buffer.length);
    void fetch(`${API_BASE}/sessions/${this.sessionId}/events`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ events }),
      keepalive: true,
    }).catch(() => {});
  }
}
