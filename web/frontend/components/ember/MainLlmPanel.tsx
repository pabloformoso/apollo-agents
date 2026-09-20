"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth";

/**
 * The main LLM: the ONE model Apollo thinks with.
 *
 * Brief extraction, session planning, the live DJ and the Algorave Mind all
 * answer with the model chosen here. It used to be two panels — a "session
 * model" and a "Mind model" — for what is one LM Studio instance, and pressing
 * both Load buttons put two copies of it on the GPU ACE shares. The Mind's
 * HTTP service is still a separate process on that host, so it keeps a
 * start/stop pair here, but it owns no model.
 */

type Model = { key: string; name: string; type: string; state: string; loaded_instances: { instance_id?: string }[]; max_context_length?: number | null; params_string?: string | null };
type Settings = { model_key: string; context_length: number; flash_attention: boolean };
type Status = { configured: boolean; provider: string; endpoint: string | null; settings: Settings; models: Model[]; selected?: Model | null; loaded_model: string | null; selected_loaded: boolean; can_manage: boolean; error: string | null };
type MindStatus = { service: string; reachable: boolean; loaded_models: string[]; busy: boolean; operation: string | null; error: string | null; uncertain: boolean; can_manage: boolean; main_llm: string };

async function request(base: string, path = "", method = "GET", body?: Settings) {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? ""}${base}${path}`, {
    method, headers: { Authorization: `Bearer ${getToken() ?? ""}`, "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Request failed");
  return data;
}

const llm = (path = "", method = "GET", body?: Settings) => request("/api/main-llm", path, method, body);
const mind = (path = "", method = "GET") => request("/api/mind", path, method);

export function MainLlmPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const [mindStatus, setMindStatus] = useState<MindStatus | null>(null);
  const [mindError, setMindError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next: Status = await llm();
        if (!cancelled) { setStatus(next); setDraft(old => old ?? next.settings); setError(null); }
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "Status unavailable"); }
      try {
        const next: MindStatus = await mind();
        if (!cancelled) { setMindStatus(next); setMindError(null); }
      } catch (e) {
        // The Mind's host controller is optional: an install without it still
        // manages the model. Say so quietly instead of alarming the operator.
        if (!cancelled) { setMindStatus(null); setMindError(e instanceof Error ? e.message : "Mind status unavailable"); }
      }
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [revision]);

  const act = async (action: "save" | "load" | "unload") => {
    setBusy(true); setError(null);
    try {
      if (action === "save" && draft) await llm("/settings", "PUT", draft);
      else if (action === "load" && draft) await llm("/actions/load", "POST", draft);
      else await llm(`/actions/${action}`, "POST");
      setRevision(n => n + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "Operation failed"); }
    finally { setBusy(false); }
  };

  const actMind = async (action: "start" | "stop") => {
    setBusy(true); setMindError(null);
    try { await mind(`/actions/${action}`, "POST"); setRevision(n => n + 1); }
    catch (e) { setMindError(e instanceof Error ? e.message : "Mind operation failed"); }
    finally { setBusy(false); }
  };

  const disabled = busy || !status?.can_manage || !status?.configured;
  const inputClass = "w-full min-w-0 border border-line bg-surf rounded p-2";
  const loaded = Boolean(status?.loaded_model);
  const selectedLoaded = Boolean(status?.selected_loaded);
  // Stop stays available while a request is unresolved: stopping the service
  // is what resolves it (the host clears the flag once the unit is down).
  const mindDisabled = busy || !mindStatus?.can_manage || mindStatus.busy;
  const mindStartDisabled = mindDisabled || Boolean(mindStatus?.uncertain);
  const mindServiceLabel = mindStatus
    ? `Service: ${mindStatus.service}${mindStatus.busy ? ` · ${mindStatus.operation}…` : ""}`
    : "Host controller not configured";
  return <section aria-label="Main LLM management" className="min-w-0 space-y-4 rounded border border-line p-4 text-sm">
    <div className="flex items-center justify-between gap-4"><h2 className="text-lg">Main LLM · brief, sessions, live DJ and Algorave Mind</h2><button type="button" className="text-xs text-mute hover:text-ember-text" onClick={() => setRevision(n => n + 1)}>Refresh</button></div>
    <p role="status">{status?.configured ? `LM Studio · ${loaded ? `loaded: ${status.loaded_model}` : "model not loaded"}` : (status ? "LM Studio management is not configured" : "Checking…")}</p>
    {status?.selected && <p className="text-mute">Selected: {status.selected.name}{status.selected.params_string ? ` · ${status.selected.params_string}` : ""}</p>}
    {status?.configured && status.can_manage && <div className="flex flex-wrap gap-2"><button type="button" disabled={disabled || selectedLoaded} onClick={() => void act("load")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Load selected model</button><button type="button" disabled={disabled || !loaded} onClick={() => void act("unload")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Unload model</button></div>}
    {draft && status && <fieldset disabled={disabled} className="space-y-3 disabled:opacity-60"><legend className="mb-2">Model settings</legend>
      <label className="block">Installed model<select className={inputClass} value={draft.model_key} onChange={e => setDraft({ ...draft, model_key: e.target.value })}>{!status.models.some(m => m.key === draft.model_key) && <option value={draft.model_key}>{draft.model_key} (not available)</option>}{status.models.filter(m => m.type === "llm" || m.type === "vlm").map(m => <option key={m.key} value={m.key}>{m.name}</option>)}</select></label>
      <label className="block">Context tokens<input className={inputClass} type="number" min={512} max={131072} step={512} value={draft.context_length} onChange={e => setDraft({ ...draft, context_length: Number(e.target.value) })} /></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={draft.flash_attention} onChange={e => setDraft({ ...draft, flash_attention: e.target.checked })} />Flash attention</label>
      <p className="text-mute">One model for everything Apollo thinks with. ACE is separate: it generates audio and shares the GPU, so unload this model before starting ACE and stop ACE before loading it. Save settings to keep the choice as the default, or load directly to apply the current selection. Loading evicts whatever is resident first: one model on the GPU, ever.</p>
      <button type="button" onClick={() => void act("save")} className="rounded border border-line px-3 py-2">Save settings</button>
    </fieldset>}
    {status && !status.can_manage && <p>Only administrators can manage the main LLM.</p>}
    {(error || status?.error) && <p role="alert" className="text-warn">{error || status?.error}</p>}

    <div aria-label="Algorave Mind service" className="space-y-2 border-t border-line pt-3">
      <h3 className="text-base">Algorave Mind service</h3>
      <p role="status">{mindServiceLabel}</p>
      {mindStatus?.can_manage && <div className="flex flex-wrap gap-2">
        <button type="button" disabled={mindStartDisabled || mindStatus.service === "active"} onClick={() => void actMind("start")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Start Mind</button>
        <button type="button" disabled={mindDisabled || mindStatus.service !== "active"} onClick={() => void actMind("stop")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Stop Mind</button>
      </div>}
      <p className="text-mute">The Mind turns an intent into Strudel on the GPU host and answers with the main LLM above. Starting it loads nothing; stopping it unloads nothing.</p>
      {mindStatus && !mindStatus.can_manage && <p>Only administrators can start or stop the Mind.</p>}
      {(mindError || mindStatus?.error || mindStatus?.uncertain) && <p role="alert" className="text-warn">{mindError || mindStatus?.error || "A Mind request is unresolved. Verify it finished on the host, then Stop Mind to clear this before unloading the model."}</p>}
    </div>
  </section>;
}
