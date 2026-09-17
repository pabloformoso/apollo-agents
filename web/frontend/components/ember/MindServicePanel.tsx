"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth";

type Settings = { model_key: string; context_length: number; gpu_fraction: number; allow_shared_gpu: boolean };
type Status = { service: string; reachable: boolean; model_loaded: boolean; loaded_model: string | null; models: { key: string; name: string }[]; settings: Settings; busy: boolean; operation: string | null; error: string | null; uncertain: boolean; can_manage: boolean };
async function request(path = "", method = "GET", body?: Settings) {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api/mind${path}`, {
    method, headers: { Authorization: `Bearer ${getToken() ?? ""}`, "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Mind request failed");
  return data;
}

/** This panel never navigates, reloads audio, or applies a generated pattern. */
export function MindServicePanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next: Status = await request();
        if (!cancelled) { setStatus(next); setDraft(old => old ?? next.settings); }
      } catch (e) {
        if (!cancelled) { setStatus(null); setError(e instanceof Error ? e.message : "Status unavailable"); }
      }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [revision]);
  const act = async (action: string) => {
    setSending(true); setError(null);
    try {
      if (action === "save" && draft) await request("/settings", "PUT", draft);
      else await request(`/actions/${action}`, "POST");
      setRevision(n => n + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "Operation failed"); }
    finally { setSending(false); }
  };
  const disabled = sending || !status?.can_manage || status.busy || status.uncertain;
  const inputClass = "w-full min-w-0 border border-line bg-surf rounded p-2";
  return <section aria-label="Mind model management" className="min-w-0 space-y-4 rounded border border-line p-4 text-sm">
    <h2 className="text-lg">Mind · Algorave / B2B</h2>
    <p role="status">{status ? `Service: ${status.service} · Model: ${status.model_loaded ? "loaded" : "unloaded"}${status.busy ? ` · ${status.operation}…` : ""}` : "Status unavailable"}</p>
    {status?.loaded_model && <p className="break-all text-mute">Loaded: {status.loaded_model}</p>}
    <div className="flex flex-wrap gap-2">
      {(["start", "stop", "load", "unload"] as const).map(action => <button key={action} type="button" disabled={disabled || ((action === "load") && status?.model_loaded) || ((action === "unload") && !status?.model_loaded)} onClick={() => void act(action)} className="rounded border border-line px-3 py-2 disabled:opacity-40">{{ start: "Start Mind", stop: "Stop Mind", load: "Load model", unload: "Unload model" }[action]}</button>)}
    </div>
    <p className="text-mute">Starting Mind does not load its model. Stopping it does not unload the model or stop ACE.</p>
    {draft && status && <fieldset disabled={disabled} className="space-y-3 disabled:opacity-60">
      <legend className="mb-2">Model settings</legend>
      <label className="block">Installed model<select className={inputClass} value={draft.model_key} onChange={e => setDraft({ ...draft, model_key: e.target.value })}>
        {!status.models.some(m => m.key === draft.model_key) && <option value={draft.model_key}>{draft.model_key} (not installed)</option>}
        {status.models.map(m => <option key={m.key} value={m.key}>{m.name}</option>)}
      </select></label>
      <label className="block">Context tokens<input className={inputClass} type="number" min={512} max={32768} step={512} value={draft.context_length} onChange={e => setDraft({ ...draft, context_length: Number(e.target.value) })} /></label>
      <label className="block">GPU offload ({Math.round(draft.gpu_fraction * 100)}%)<input className="w-full" type="range" min={0} max={1} step={0.05} value={draft.gpu_fraction} onChange={e => setDraft({ ...draft, gpu_fraction: Number(e.target.value) })} /></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={draft.allow_shared_gpu} onChange={e => setDraft({ ...draft, allow_shared_gpu: e.target.checked })} />Allow Mind and ACE to coexist</label>
      <p className="text-mute">GPU offload is not a VRAM limit. Both models may run out of memory; reduce offload/context if needed. 0% uses CPU. No model is automatically stopped.</p>
      <button type="button" onClick={() => void act("save")} className="rounded border border-line px-3 py-2">Save settings</button>
      <p className="text-mute">Model, context and offload changes apply on the next load. Unload first to replace the current model.</p>
    </fieldset>}
    {status && !status.can_manage && <p>Only administrators can manage models and configuration.</p>}
    {(error || status?.error || status?.uncertain) && <p role="alert" className="text-warn">{error || status?.error || "Model operation unresolved. Check host logs before retrying."}</p>}
  </section>;
}
