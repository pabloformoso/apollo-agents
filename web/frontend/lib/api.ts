import { getToken } from "./auth";
import type { Catalog, SessionState } from "./types";

const BASE = `${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api`;

async function req<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...((options.headers as Record<string, string>) ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail ?? "Request failed");
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// Auth
export const register = (username: string, email: string, password: string) =>
  req<{ access_token: string; user: { id: number; username: string; email: string } }>(
    "/auth/register",
    { method: "POST", body: JSON.stringify({ username, email, password }) },
  );

export const login = (username: string, password: string) =>
  req<{ access_token: string; user: { id: number; username: string; email: string } }>(
    "/auth/login",
    { method: "POST", body: JSON.stringify({ username, password }) },
  );

export const me = () =>
  req<{ id: number; username: string; email: string }>("/auth/me");

// Sessions
export const createSession = () =>
  req<SessionState>("/sessions", { method: "POST" });

export const listSessions = () =>
  req<SessionState[]>("/sessions");

export const getSession = (id: string) =>
  req<SessionState>(`/sessions/${id}`);

export const deleteSession = (id: string) =>
  req<void>(`/sessions/${id}`, { method: "DELETE" });

export const rateSession = (
  id: string,
  rating: number,
  notes?: string,
  transition_ratings?: unknown[],
) =>
  req<{ ok: boolean }>(`/sessions/${id}/rate`, {
    method: "POST",
    body: JSON.stringify({ rating, notes, transition_ratings }),
  });

// Catalog
export const getCatalog = (genre?: string) => {
  const qs = genre ? `?genre=${encodeURIComponent(genre)}` : "";
  return req<Catalog>(`/catalog${qs}`);
};

// Audio streaming — `<audio>` can't set Authorization headers, so the JWT
// goes in the query string (same trick as the WebSocket auth).
export const streamUrl = (trackId: string): string => {
  const token = getToken() ?? "";
  return `${BASE}/tracks/${encodeURIComponent(trackId)}/stream?token=${encodeURIComponent(token)}`;
};
