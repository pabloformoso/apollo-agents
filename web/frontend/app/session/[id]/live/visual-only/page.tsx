"use client";
/**
 * /session/{id}/live/visual-only — OBS-friendly fullscreen visual layer.
 *
 * This route renders ONLY the ``<VisualLayer>``: no header, no chat, no
 * action buttons.  An OBS browser source can capture it directly to
 * project the visualizer into a stream without any chrome.
 *
 * Auth, WS, and audio plumbing are identical to the regular ``/live``
 * route (we re-use ``useLiveSession`` so the deck audio + currentTrack
 * are populated by the same mechanism).  The component is intentionally
 * minimal — every interactive surface lives on the regular ``/live``
 * page; this one is read-only by design.
 *
 * v2.6 will plug a broadcast encoder into a sibling route without
 * touching this file.  That's the whole point of the OBS-friendly split.
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";

import VisualLayer from "@/components/VisualLayer";
import { useAuth } from "@/lib/auth";
import { useAuthQueryBootstrap } from "@/lib/auth-bootstrap";
import { useLiveSession } from "@/lib/live";

export default function VisualOnlyPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params?.id ?? null;
  const { user, hydrated } = useAuth();
  // OBS Browser Sources don't share localStorage with the operator's
  // browser, so the chrome-less stream URL accepts an `?auth=<jwt>`
  // hand-off. The hook persists the token and reloads with the URL
  // cleaned up so useAuth picks it up normally.
  const { bootstrapping } = useAuthQueryBootstrap();

  // Auth gate (mirrors the parent /live page). Wait for the URL-token
  // bootstrap so we don't bounce to /login before saveAuth lands.
  useEffect(() => {
    if (!hydrated || bootstrapping) return;
    if (!user) {
      router.replace("/login");
    }
  }, [hydrated, bootstrapping, user, router]);

  // Defer opening the WS until after hydration to keep SSR markup stable.
  const liveSessionId = hydrated && user ? sessionId : null;
  const live = useLiveSession(liveSessionId);

  // Track autoplay-blocked state — OBS captures don't interact, so we
  // surface a small click-to-start affordance for the operator before
  // they start the stream.
  const [dismissed, setDismissed] = useState(false);

  if (!hydrated) return null;
  if (!user) return null;

  return (
    <main
      data-testid="visual-only-root"
      className="fixed inset-0 bg-black overflow-hidden"
    >
      <div className="absolute inset-0">
        <VisualLayer audioRef={live.audioRef} currentTrack={live.currentTrack} />
      </div>

      {live.autoplayBlocked && !dismissed ? (
        <div
          data-testid="visual-only-resume"
          className="absolute inset-0 flex items-center justify-center bg-black/70 z-50"
        >
          <button
            onClick={() => {
              live.resumePlayback();
              setDismissed(true);
            }}
            className="bg-neon text-[#0a0a0f] px-8 py-4 rounded text-sm font-bold uppercase tracking-widest hover:bg-neon-dim transition-colors"
          >
            Click to start
          </button>
        </div>
      ) : null}
    </main>
  );
}
