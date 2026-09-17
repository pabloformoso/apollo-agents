"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth";

type Preparation = {
  status: "unprepared" | "queued" | "running" | "ready" | "failed";
  error: string | null;
};

export function TrackPreparation({ trackId }: { trackId: string }) {
  const [state, setState] = useState<Preparation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const url = `${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api/generator/tracks/${encodeURIComponent(trackId)}/processing`;

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    async function poll() {
      try {
        const response = await fetch(url, {
          headers: { Authorization: `Bearer ${getToken()}` }, signal: controller.signal,
        });
        if (!response.ok) throw new Error("Cannot read audio preparation status.");
        const result: Preparation = await response.json();
        if (!disposed) {
          setState(result);
          setError(null);
          if (result.status === "ready" || result.status === "failed" || result.status === "unprepared") return;
        }
      } catch {
        if (!disposed) setError("Cannot read audio preparation status. Retrying…");
      }
      if (!disposed) timer = setTimeout(poll, 3000);
    }
    void poll();
    return () => { disposed = true; controller.abort(); clearTimeout(timer); };
  }, [url, revision]);

  async function retry() {
    setBusy(true);
    try {
      const response = await fetch(url, { method: "POST", headers: { Authorization: `Bearer ${getToken()}` } });
      if (!response.ok) throw new Error(response.status === 403 ? "Only a catalog publisher can prepare tracks." : "Could not queue audio preparation.");
      setState(await response.json());
      setError(null);
      setRevision((value) => value + 1);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not queue audio preparation.");
    } finally {
      setBusy(false);
    }
  }

  const labels = {
    queued: "Queued for audio preparation — unavailable for sessions.",
    running: "Preparing audio: duration, beatgrid, waveform and MP3…",
    ready: "Audio ready for sessions.",
    failed: "Audio preparation failed — unavailable for sessions.",
    unprepared: "Audio has not been prepared for sessions yet.",
  };
  return (
    <div className="text-[11px] text-mute leading-[1.45] mb-3" data-testid="track-preparation">
      <p role="status">{state ? labels[state.status] : "Checking audio preparation…"}</p>
      {(error || state?.error) && <p role="alert">{error || state?.error}</p>}
      {(state?.status === "failed" || state?.status === "unprepared") && (
        <button type="button" disabled={busy} onClick={retry} className="text-ember hover:underline disabled:opacity-50">
          {busy ? "Queueing…" : state.status === "failed" ? "Retry audio preparation" : "Prepare audio for sessions"}
        </button>
      )}
    </div>
  );
}
