"use client";
/**
 * Apollo v2.6.0 — auto-pick a session for the redesign routes.
 *
 * The new flat routes (`/curate`, `/editor`, `/render`, `/live`) expect a
 * `?session=<id>` query param. When the user lands on one of them via the
 * top nav (which has no param), we auto-pick the most relevant session
 * from their library so the screen renders with real data instead of
 * bouncing to the dashboard.
 *
 * Selection rules
 * ---------------
 *   - "playlist": newest session that has a non-empty playlist. Used by
 *     Curate / Editor / Render / Live — they only make sense with tracks.
 *   - "editing-or-later": newest session in editing/rating/complete phase.
 *     Specifically for Live, where the agent has produced a playable set.
 *
 * If nothing matches, the caller should render an "empty library" state
 * with a CTA to /brief.
 */
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { listSessions } from "./api";
import type { SessionState } from "./types";
import { useAuth } from "./auth";

export type AutoSessionMode = "playlist" | "editing-or-later";

function pickSession(
  sessions: SessionState[],
  mode: AutoSessionMode,
): SessionState | null {
  const sorted = [...sessions].sort((a, b) =>
    (b.created_at || "").localeCompare(a.created_at || ""),
  );
  if (mode === "editing-or-later") {
    const PHASES = new Set([
      "editing",
      "rating",
      "complete",
      "validating",
      "building",
    ]);
    return (
      sorted.find(
        (s) => PHASES.has(s.phase) && (s.playlist?.length ?? 0) > 0,
      ) ?? null
    );
  }
  // "playlist" — anything with tracks.
  return sorted.find((s) => (s.playlist?.length ?? 0) > 0) ?? null;
}

export type AutoSessionResult =
  | { status: "loading" }
  | { status: "redirect" } // bouncing to /brief or login
  | { status: "ready"; sessionId: string };

/**
 * Resolves the active session id for a screen that needs one.
 *
 * If `?session=<id>` is in the URL, returns it directly. Otherwise lists
 * the user's sessions and picks the most relevant one per `mode`. If
 * nothing matches, redirects to `/brief` (start a new set) and returns a
 * `redirect` marker.
 */
export function useAutoSession(mode: AutoSessionMode): AutoSessionResult {
  const router = useRouter();
  const params = useSearchParams();
  const { user, hydrated } = useAuth();
  const explicit = params.get("session");
  const [resolved, setResolved] = useState<string | null>(null);
  const [redirecting, setRedirecting] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.replace("/login");
      setRedirecting(true);
      return;
    }
    if (explicit) {
      setResolved(explicit);
      return;
    }
    let cancelled = false;
    listSessions()
      .then((sessions) => {
        if (cancelled) return;
        const pick = pickSession(sessions, mode);
        if (pick) {
          // Reflect the chosen session in the URL so reloads stay sticky
          // and deep-links share cleanly. Use replace() so the back
          // button doesn't ping-pong through the auto-pick.
          const path = window.location.pathname;
          router.replace(`${path}?session=${pick.id}`);
          setResolved(pick.id);
        } else {
          router.replace("/brief");
          setRedirecting(true);
        }
      })
      .catch(() => {
        if (cancelled) return;
        router.replace("/dashboard");
        setRedirecting(true);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, explicit, mode, router]);

  if (redirecting) return { status: "redirect" };
  if (resolved) return { status: "ready", sessionId: resolved };
  return { status: "loading" };
}
