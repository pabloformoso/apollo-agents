"use client";
/**
 * GreetingOverlay (v3.7.0) — on-stream toast for new chatters.
 *
 * Consumes the ``greetings`` feed from ``useLiveSession`` and renders at
 * most ONE calm toast at a time, bottom-left, with a slow fade in/out.
 * This paints inside the /live page, so the OBS Browser Source captures
 * it with zero OBS configuration.
 *
 * All decision logic (per-name templates, burst coalescing thresholds)
 * lives in ``lib/greetings.ts`` as pure functions; this component only
 * owns timing. Timing model:
 *
 *   ingest → pending queue → [toast visible TOAST_DURATION_MS]
 *          → [quiet gap TOAST_GAP_MS] → next toast (coalesced if 3+)
 *
 * The fade is a CSS keyframe animation spanning the full toast duration
 * (fade in over the first ~8%, out over the last ~8%) so there's no
 * extra visibility state to juggle.
 */

import { useEffect, useRef, useState } from "react";

import {
  Greeting,
  TOAST_DURATION_MS,
  TOAST_GAP_MS,
  nextToast,
} from "@/lib/greetings";

interface GreetingOverlayProps {
  greetings: Greeting[];
}

export default function GreetingOverlay({ greetings }: GreetingOverlayProps) {
  const [toast, setToast] = useState<{ text: string; key: number } | null>(
    null,
  );
  const pendingRef = useRef<Greeting[]>([]);
  const lastIdRef = useRef(0);
  const busyRef = useRef(false);
  const timersRef = useRef<number[]>([]);
  const toastKeyRef = useRef(0);

  // Drain loop — displays one toast, waits duration + gap, repeats.
  // Only ever entered from timer/deferred callbacks (never synchronously
  // from an effect body) so setState stays in event-handler position.
  const drainRef = useRef<() => void>(() => {});
  drainRef.current = () => {
    if (busyRef.current) return;
    const plan = nextToast(pendingRef.current);
    if (!plan) return;
    busyRef.current = true;
    pendingRef.current = pendingRef.current.slice(plan.consumed);
    toastKeyRef.current += 1;
    setToast({ text: plan.text, key: toastKeyRef.current });
    const hide = window.setTimeout(() => {
      setToast(null);
      const next = window.setTimeout(() => {
        busyRef.current = false;
        drainRef.current();
      }, TOAST_GAP_MS);
      timersRef.current.push(next);
    }, TOAST_DURATION_MS);
    timersRef.current.push(hide);
  };

  // Ingest new feed entries (identified by monotonic id) and kick the
  // drain on a microtask-ish timer so no setState runs in the effect body.
  useEffect(() => {
    let added = false;
    for (const g of greetings) {
      if (g.id > lastIdRef.current) {
        pendingRef.current.push(g);
        lastIdRef.current = g.id;
        added = true;
      }
    }
    if (!added) return;
    const kick = window.setTimeout(() => drainRef.current(), 0);
    timersRef.current.push(kick);
    return () => {
      window.clearTimeout(kick);
    };
  }, [greetings]);

  // Unmount cleanup — kill every outstanding timer.
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const t of timers) window.clearTimeout(t);
      timers.length = 0;
    };
  }, []);

  if (!toast) return null;

  return (
    <div
      className="pointer-events-none fixed bottom-6 left-6 z-50"
      data-testid="greeting-overlay"
    >
      <div
        key={toast.key}
        data-testid="greeting-toast"
        className="px-4 py-2 rounded-lg border border-neon/40 bg-black/70 backdrop-blur-sm text-neon text-sm font-pixel shadow-lg"
        style={{
          animation: `greeting-fade ${TOAST_DURATION_MS}ms ease both`,
        }}
      >
        <span aria-hidden="true" className="mr-2">
          👋
        </span>
        {toast.text}
      </div>
      <style>{`
        @keyframes greeting-fade {
          0% { opacity: 0; transform: translateY(6px); }
          8% { opacity: 1; transform: translateY(0); }
          92% { opacity: 1; transform: translateY(0); }
          100% { opacity: 0; transform: translateY(-4px); }
        }
      `}</style>
    </div>
  );
}
