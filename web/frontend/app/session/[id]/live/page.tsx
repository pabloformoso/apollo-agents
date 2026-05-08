"use client";
/**
 * /session/{id}/live — v2.5.1 live performance route.
 *
 * Auth-gated via useAuth() (the canonical v2.4 pattern). The component
 * waits for hydration before opening the WebSocket so server-rendered
 * markup matches the client and the WS isn't started twice.
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

import LiveStage from "@/components/LiveStage";
import { useAuth } from "@/lib/auth";
import { getSession } from "@/lib/api";
import { useLiveSession } from "@/lib/live";
import type { SessionState } from "@/lib/types";

export default function LiveSessionPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params?.id ?? null;
  const { user, hydrated } = useAuth();

  const [session, setSession] = useState<SessionState | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Auth gate — only redirect once hydrated so logged-in users aren't
  // bounced during the brief pre-hydration render where `user` is still
  // null. This is the same pattern used by /session/[id]/page.tsx.
  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.replace("/login");
    }
  }, [hydrated, user, router]);

  useEffect(() => {
    if (!hydrated || !user || !sessionId) return;
    let cancelled = false;
    getSession(sessionId)
      .then((s) => {
        if (cancelled) return;
        setSession(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // setState inside a promise callback is allowed by
        // react-hooks/set-state-in-effect (v7).
        setLoadError(err instanceof Error ? err.message : "Failed to load session");
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, sessionId]);

  // Only open the WS once we have a confirmed session (so we know the
  // playlist is on the server — the live WS rejects empty playlists).
  const liveSessionId = session && sessionId ? sessionId : null;
  const live = useLiveSession(liveSessionId);

  if (!hydrated) {
    return (
      <main className="min-h-screen p-8 text-muted text-xs">
        Loading...
      </main>
    );
  }
  if (!user) {
    return null;
  }

  if (loadError) {
    return (
      <main className="min-h-screen p-8 space-y-4">
        <p className="text-danger text-sm">{loadError}</p>
        <Link
          href={`/session/${sessionId}`}
          className="text-neon text-xs uppercase tracking-widest"
        >
          Back to session
        </Link>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="min-h-screen p-8 text-muted text-xs">
        Loading session...
      </main>
    );
  }

  return (
    <main className="min-h-screen pb-24">
      <div className="px-4 md:px-8 pt-4">
        <Link
          href={`/session/${sessionId}`}
          className="text-[10px] tracking-widest uppercase text-muted hover:text-neon transition-colors"
        >
          ← Back to session
        </Link>
      </div>
      <LiveStage
        live={live}
        durationMin={session.duration_min}
        sessionName={session.session_name}
      />
    </main>
  );
}
