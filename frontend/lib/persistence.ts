// Persists per-content interaction state (quiz answers, flashcard position, etc.) in
// localStorage so revisiting the same generated content — even across separate learning
// sessions — shows where you left off instead of resetting every time.

const PREFIX = "study:content-state:";

export function loadContentState<T>(contentId: string, key: string): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${PREFIX}${contentId}:${key}`);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function saveContentState<T>(contentId: string, key: string, value: T): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${PREFIX}${contentId}:${key}`, JSON.stringify(value));
  } catch {
    // best-effort — localStorage can be full/disabled, not worth surfacing to the user
  }
}
