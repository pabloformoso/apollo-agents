"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createPlaylist as apiCreate,
  deletePlaylist as apiDelete,
  listPlaylists,
} from "@/lib/api";
import { clearAuth, getUser } from "@/lib/auth";
import type { Playlist } from "@/lib/types";

export default function PlaylistsPage() {
  const router = useRouter();
  const [user, setUser] = useState<ReturnType<typeof getUser>>(null);
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPlaylists(await listPlaylists());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load playlists");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const u = getUser();
    if (!u) {
      router.push("/login");
      return;
    }
    setUser(u);
    load();
  }, [load, router]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const p = await apiCreate(trimmed);
      setPlaylists((prev) => [p, ...prev]);
      setName("");
      setCreating(false);
      router.push(`/playlists/${p.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Create failed");
    }
  }

  async function handleDelete(id: number, e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm("Delete this playlist? This cannot be undone.")) return;
    try {
      await apiDelete(id);
      setPlaylists((prev) => prev.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  }

  if (!user) return null;

  return (
    <div className="min-h-screen p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="font-pixel text-neon text-base glow tracking-widest">
            APOLLO / PLAYLISTS
          </h1>
          <p className="text-muted text-xs mt-1">
            {loading ? "Loading…" : `${playlists.length} playlists`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/dashboard")}
            className="text-muted text-xs hover:text-[#e2e2ff] transition-colors"
          >
            Dashboard →
          </button>
          <button
            onClick={() => router.push("/catalog")}
            className="text-muted text-xs hover:text-neon transition-colors"
          >
            Catalog →
          </button>
          <button
            onClick={() => setCreating((v) => !v)}
            data-testid="new-playlist-toggle"
            className="bg-neon text-[#0a0a0f] px-4 py-2 rounded text-xs font-bold tracking-widest uppercase hover:bg-neon-dim transition-colors"
          >
            + New
          </button>
          <button
            onClick={() => {
              clearAuth();
              router.push("/login");
            }}
            className="text-muted text-xs hover:text-[#e2e2ff] transition-colors"
          >
            Sign Out
          </button>
        </div>
      </div>

      {creating && (
        <form
          onSubmit={handleCreate}
          className="mb-4 flex items-center gap-2 bg-surface border border-border rounded p-3"
        >
          <input
            autoFocus
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Playlist name"
            maxLength={100}
            data-testid="new-playlist-name"
            className="flex-1 bg-[#0a0a0f] border border-border rounded px-2 py-1 text-xs text-[#e2e2ff] focus:border-neon focus:outline-none"
          />
          <button
            type="submit"
            disabled={!name.trim()}
            data-testid="new-playlist-submit"
            className="text-neon text-xs px-3 py-1 disabled:opacity-50 hover:underline"
          >
            Create
          </button>
          <button
            type="button"
            onClick={() => {
              setCreating(false);
              setName("");
            }}
            className="text-muted text-xs px-2 py-1 hover:text-[#e2e2ff]"
          >
            Cancel
          </button>
        </form>
      )}

      {error && (
        <div className="border border-danger rounded p-3 text-xs text-danger mb-4">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-muted text-xs animate-pulse">Loading…</p>
      ) : playlists.length === 0 ? (
        <div className="border border-dashed border-border rounded p-12 text-center">
          <p className="text-muted text-sm mb-4">No playlists yet.</p>
          <button
            onClick={() => setCreating(true)}
            className="text-neon text-xs hover:underline"
          >
            Create your first playlist →
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          {playlists.map((p) => (
            <div
              key={p.id}
              onClick={() => router.push(`/playlists/${p.id}`)}
              className="bg-surface border border-border rounded p-4 cursor-pointer hover:border-neon transition-colors group flex items-center justify-between"
              data-testid={`playlist-row-${p.id}`}
            >
              <div>
                <p className="text-sm text-[#e2e2ff] font-bold">{p.name}</p>
                <p className="text-xs text-muted mt-0.5">
                  {p.track_count} {p.track_count === 1 ? "track" : "tracks"} ·
                  updated {new Date(p.updated_at).toLocaleDateString()}
                </p>
              </div>
              <button
                onClick={(e) => handleDelete(p.id, e)}
                className="text-muted hover:text-danger text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                aria-label={`Delete ${p.name}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
