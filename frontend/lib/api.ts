import { clearToken, getToken } from "@/lib/auth";
import type {
  AuthResponse,
  ChatDetailOut,
  ChatOut,
  GeneratedContentOut,
  MaterialSourceOut,
  Mode,
  SessionCompleteResponse,
  SessionDetailOut,
  SessionOut,
  StatsOut,
  StillEngagedResponse,
  SuggestModeOut,
  TelemetryEvent,
  TutorMessageOut,
  TutorReplyOut,
  UserOut,
} from "@/types/api";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/** Authorization header for the current token, or {} when logged out. Exported so the
 * telemetry collector's keepalive fetch can reuse it. */
export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    // An expired/invalid token on a normal call — drop it and bounce to login. Auth
    // endpoints are exempt so a wrong password surfaces as an ApiError for the form.
    if (res.status === 401 && !path.startsWith("/auth/") && getToken()) {
      clearToken();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Auth

export function register(email: string, password: string, displayName?: string): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name: displayName || null }),
  });
}

export function login(email: string, password: string): Promise<AuthResponse> {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

export function getMe(): Promise<UserOut> {
  return request<UserOut>("/auth/me");
}

// Chats

export function createChat(): Promise<ChatOut> {
  return request<ChatOut>("/chats", { method: "POST" });
}

export function listChats(): Promise<ChatOut[]> {
  return request<ChatOut[]>("/chats");
}

export function getChat(chatId: string): Promise<ChatDetailOut> {
  return request<ChatDetailOut>(`/chats/${chatId}`);
}

// Sources

export function addFileSource(chatId: string, file: File): Promise<MaterialSourceOut> {
  const form = new FormData();
  form.append("file", file);
  return request<MaterialSourceOut>(`/chats/${chatId}/sources/file`, { method: "POST", body: form });
}

export function addLinkSource(
  chatId: string,
  sourceType: "youtube" | "website",
  url: string
): Promise<MaterialSourceOut> {
  return request<MaterialSourceOut>(`/chats/${chatId}/sources/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_type: sourceType, url }),
  });
}

export function addTextSource(chatId: string, text: string): Promise<MaterialSourceOut> {
  return request<MaterialSourceOut>(`/chats/${chatId}/sources/text`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

export function deleteSource(chatId: string, sourceId: string): Promise<void> {
  return request<void>(`/chats/${chatId}/sources/${sourceId}`, { method: "DELETE" });
}

// Generation / suggestion

export function suggestMode(chatId: string): Promise<SuggestModeOut> {
  return request<SuggestModeOut>(`/chats/${chatId}/suggest-mode`);
}

export function generateContent(chatId: string, mode: Mode, options?: object): Promise<GeneratedContentOut> {
  return request<GeneratedContentOut>(`/chats/${chatId}/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, options: options ?? null }),
  });
}

// Polls a generation that returned status "pending" (currently only comic mode — panel image
// generation runs in the background). Used with pollGeneratedContent below.
export function getGeneratedContent(contentId: string): Promise<GeneratedContentOut> {
  return request<GeneratedContentOut>(`/generated-content/${contentId}`);
}

// Sessions / telemetry

export function createSession(generatedContentId: string): Promise<SessionOut> {
  return request<SessionOut>("/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ generated_content_id: generatedContentId }),
  });
}

export function getSession(sessionId: string): Promise<SessionDetailOut> {
  return request<SessionDetailOut>(`/sessions/${sessionId}`);
}

export function postEvents(sessionId: string, events: TelemetryEvent[]): Promise<void> {
  return request<void>(`/sessions/${sessionId}/events`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ events }),
  });
}

export function completeSession(sessionId: string): Promise<SessionCompleteResponse> {
  return request<SessionCompleteResponse>(`/sessions/${sessionId}/complete`, { method: "PATCH" });
}

export function postStillEngaged(sessionId: string, stillEngaged: boolean): Promise<StillEngagedResponse> {
  return request<StillEngagedResponse>(`/sessions/${sessionId}/still-engaged`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ still_engaged: stillEngaged }),
  });
}

// Stats

export function getStats(): Promise<StatsOut> {
  return request<StatsOut>("/stats");
}

// Tutor chat (local LLM, right-side panel on every session)

export function getTutorMessages(chatId: string): Promise<TutorMessageOut[]> {
  return request<TutorMessageOut[]>(`/chats/${chatId}/tutor/messages`);
}

export function sendTutorMessage(chatId: string, content: string): Promise<TutorReplyOut> {
  return request<TutorReplyOut>(`/chats/${chatId}/tutor/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
}
