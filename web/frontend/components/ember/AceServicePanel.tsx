"use client";

import { useEffect, useRef, useState } from "react";
import { controlAceService, getAceService, type AceServiceStatus } from "@/lib/generator";
import { Btn } from "./primitives";

const LABELS = {
  stopped: "Stopped", starting: "Starting…", running: "Ready",
  stopping: "Stopping…", failed: "Service failed",
  unresponsive: "Waiting for ACE", unknown: "Status unavailable",
};

/** Visible even when ACE is off: the operator must be able to turn it on. */
export function AceServicePanel() {
  const [status, setStatus] = useState<AceServiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const ready = useRef<boolean | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await getAceService();
        if (cancelled) return;
        setStatus(next);
        setReadError(null);
        if (ready.current !== next.ready) {
          ready.current = next.ready;
          window.dispatchEvent(new Event("apollo-generator-status"));
        }
      } catch (e) {
        if (cancelled) return;
        setStatus(null); // Never leave stale action buttons enabled.
        setReadError(e instanceof Error ? e.message : "Could not read ACE status.");
      }
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [revision, busy]);

  const act = async (action: "start" | "stop") => {
    setBusy(true);
    setError(null);
    try {
      const next = await controlAceService(action);
      if (mounted.current) setStatus((s) => s ? { ...s, ...next } : null);
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : "ACE operation failed.");
    } finally {
      if (mounted.current) {
        setBusy(false);
        setRevision((n) => n + 1);
      }
    }
  };

  const startable = status && ["stopped", "failed"].includes(status.state);
  const stoppable = status?.state === "running" && status.queued === 0 &&
    status.running === 0 && status.pending_results === 0;
  const blocked = busy || !status?.reachable || status.blocked_by_live;

  return (
    <section aria-label="ACE service" className="mt-6 max-w-[660px] border border-line rounded p-4">
      <div className="flex items-center justify-between gap-4">
        <p className="font-mono text-xs m-0" role="status">
          ACE-Step · {status ? (status.configured ? LABELS[status.state] : "Manual control") : (readError ? "Status unavailable" : "Checking…")}
        </p>
        <button type="button" className="text-xs text-mute hover:text-ember-text"
          onClick={() => { setError(null); setRevision((n) => n + 1); }}>Refresh</button>
      </div>
      {status?.ready && <p className="text-xs text-mute mt-2">
        {status.loaded ? "Models loaded" : "Models load on your first generation"}
        {status.queued !== null && status.running !== null && ` · ${status.queued} queued · ${status.running} running`}
      </p>}
      {status?.reason && <p className="text-xs text-mute mt-2">{status.reason}</p>}
      {status?.blocked_by_live && <p className="text-xs text-warn mt-2">A set is on air. ACE control is locked until it ends.</p>}
      {Boolean(status?.pending_results) && <p className="text-xs text-mute mt-2">
        {status?.pending_results} batch(es) still pending. Resume them in the library before stopping ACE.
      </p>}
      {status?.configured && status.can_manage && <div className="flex gap-3 mt-3">
        <Btn kind="ghost" disabled={blocked || !startable} onClick={() => void act("start")}>Start ACE</Btn>
        <Btn kind="ghost" disabled={blocked || !stoppable} onClick={() => void act("stop")}>Stop ACE</Btn>
      </div>}
      {status?.configured && status.ready && <p className="text-xs text-mute mt-2">
        Stopping frees the generator. Unpublished takes need ACE running to play; catalog tracks remain available.
      </p>}
      {status?.configured && !status.can_manage && <p className="text-xs text-mute mt-2">An administrator can start or stop ACE.</p>}
      {error && <p role="alert" className="text-xs text-warn mt-2">{error}</p>}
      {readError && <p role="alert" className="text-xs text-warn mt-2">{readError}</p>}
      {busy && <p className="text-xs text-mute mt-2">Sending command…</p>}
    </section>
  );
}
