import type { TelemetryEvent, TelemetryEventType } from "@/types/api";

export function makeEvent(type: TelemetryEventType, payload: Record<string, unknown> = {}): TelemetryEvent {
  return { event_type: type, payload, client_ts: new Date().toISOString() };
}
