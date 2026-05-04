import { getToken } from "./auth";
import type { Catalog, Playlist, PlaylistDetail, SessionState } from "./types";

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

// Playlists (v2.2.1)
export const listPlaylists = () => req<Playlist[]>("/playlists");

export const createPlaylist = (name: string) =>
  req<Playlist>("/playlists", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const getPlaylist = (id: number) =>
  req<PlaylistDetail>(`/playlists/${id}`);

export const renamePlaylist = (id: number, name: string) =>
  req<Playlist>(`/playlists/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });

export const deletePlaylist = (id: number) =>
  req<void>(`/playlists/${id}`, { method: "DELETE" });

export const addTracks = (id: number, trackIds: string[]) =>
  req<{ playlist_id: number; track_count: number }>(
    `/playlists/${id}/tracks`,
    { method: "POST", body: JSON.stringify({ track_ids: trackIds }) },
  );

export const removeTrack = (id: number, trackId: string) =>
  req<void>(`/playlists/${id}/tracks/${encodeURIComponent(trackId)}`, {
    method: "DELETE",
  });

export const reorderTracks = (id: number, trackIds: string[]) =>
  req<{ id: number; track_ids: string[]; updated_at: string }>(
    `/playlists/${id}/order`,
    { method: "PUT", body: JSON.stringify({ track_ids: trackIds }) },
  );

// Per-user track ratings (1–5). DELETE is idempotent so the UI can fire it
// on every "click filled star" without first checking server state.
export const setRating = (trackId: string, rating: number) =>
  req<{ track_id: string; rating: number }>(
    `/tracks/${encodeURIComponent(trackId)}/rating`,
    { method: "PUT", body: JSON.stringify({ rating }) },
  );

export const clearRating = (trackId: string) =>
  req<void>(`/tracks/${encodeURIComponent(trackId)}/rating`, {
    method: "DELETE",
  });
