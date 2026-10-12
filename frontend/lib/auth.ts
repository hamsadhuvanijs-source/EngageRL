// Bearer token storage. Kept in localStorage so a reload stays logged in; SSR-guarded like
// lib/persistence.ts. The token is opaque and revocable server-side (see backend
// app/models/auth_token.py).

const TOKEN_KEY = "engagerl:token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // ignore — private mode / disabled storage
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}
