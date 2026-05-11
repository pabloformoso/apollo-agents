"use client";
/**
 * Apollo v2.6.0 — Playlists list.
 * Ember design-system port. Same data + behaviour, new visual layer.
 * `data-testid` hooks preserved verbatim for E2E.
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  createPlaylist as apiCreate,
  deletePlaylist as apiDelete,
  listPlaylists,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Playlist } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import { Btn, Crumb } from "@/components/ember/primitives";

export default function PlaylistsPage() {
  const router = useRouter();
  const { user, hydrated } = useAuth();
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.push("/login");
      return;
    }
    let cancelled = false;
    listPlaylists()
      .then((p) => {
        if (cancelled) return;
        setPlaylists(p);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Failed to load playlists");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, router]);

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
    <Shell username={user.username}>
      <section className="px-[60px] pt-10 pb-6 border-b border-line">
        <div className="flex items-end justify-between gap-6">
          <div>
            <Crumb>
              library · {loading ? "loading…" : `${playlists.length} playlists`}
            </Crumb>
            <h1 className="font-display italic font-normal text-[64px] leading-[0.95] tracking-display-tight m-0 mt-2">
              Playlists<span className="text-ember">.</span>
            </h1>
          </div>
          <Btn
            data-testid="new-playlist-toggle"
            onClick={() => setCreating((v) => !v)}
          >
            + New playlist
          </Btn>
        </div>
      </section>

      {creating && (
        <section className="px-[60px] pt-6">
          <form
            onSubmit={handleCreate}
            className="flex items-center gap-3 border border-line2 px-4 py-3 bg-surf"
          >
            <Crumb tone="ember">name</Crumb>
            <input
              autoFocus
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="A name for the playlist…"
              maxLength={100}
              data-testid="new-playlist-name"
              className="flex-1 bg-transparent border-0 text-cream
                font-display italic text-xl
                outline-none placeholder:text-faint"
            />
            <Btn
              type="submit"
              disabled={!name.trim()}
              data-testid="new-playlist-submit"
              className="px-4 py-2 text-xs"
            >
              Create
            </Btn>
            <button
              type="button"
              onClick={() => {
                setCreating(false);
                setName("");
              }}
              className="font-mono text-[11px] text-faint uppercase tracking-mono hover:text-ember-text transition-colors"
            >
              cancel
            </button>
          </form>
        </section>
      )}

      {error && (
        <div className="mx-[60px] mt-4 border border-ember p-4 font-mono text-xs text-ember">
          {error}
        </div>
      )}

      <section className="px-[60px] py-8 flex-1">
        {loading ? (
          <p className="font-mono text-xs text-faint uppercase tracking-mono">
            loading…
          </p>
        ) : playlists.length === 0 ? (
          <div className="border border-dashed border-line2 p-12 text-center">
            <p className="text-mute text-sm mb-4">No playlists yet.</p>
            <button
              onClick={() => setCreating(true)}
              className="font-display italic text-base text-ember hover:text-ember-dark transition-colors"
            >
              Create your first playlist →
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {playlists.map((p) => (
              <article
                key={p.id}
                onClick={() => router.push(`/playlists/${p.id}`)}
                className="group bg-surf border border-line p-5 cursor-pointer hover:border-ember transition-colors flex items-start justify-between gap-4"
                data-testid={`playlist-row-${p.id}`}
              >
                <div className="min-w-0 flex-1">
                  <h3 className="font-display italic text-2xl text-ember-text leading-[1.1] truncate">
                    {p.name}
                  </h3>
                  <p className="font-mono text-[11px] text-faint uppercase tracking-mono mt-2">
                    {p.track_count}{" "}
                    {p.track_count === 1 ? "track" : "tracks"} · updated{" "}
                    {new Date(p.updated_at).toLocaleDateString()}
                  </p>
                </div>
                <button
                  onClick={(e) => handleDelete(p.id, e)}
                  className="text-faint hover:text-ember text-base opacity-0 group-hover:opacity-100 transition-opacity"
                  aria-label={`Delete ${p.name}`}
                >
                  ✕
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
    </Shell>
  );
}
