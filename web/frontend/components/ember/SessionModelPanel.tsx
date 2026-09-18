"use client";

import { useEffect, useState } from "react";
import { getToken } from "@/lib/auth";

type Model = { key: string; name: string; type: string; state: string; loaded_instances: { instance_id?: string }[]; max_context_length?: number | null; params_string?: string | null };
type Settings = { model_key: string; context_length: number; flash_attention: boolean };
type Status = { configured: boolean; provider: string; endpoint: string | null; settings: Settings; models: Model[]; selected?: Model | null; loaded_model: string | null; selected_loaded: boolean; can_manage: boolean; error: string | null };

async function request(path = "", method = "GET", body?: Settings) {
  const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api/session-model${path}`, {
    method, headers: { Authorization: `Bearer ${getToken() ?? ""}`, "Content-Type": "application/json" },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Session model request failed");
  return data;
}

export function SessionModelPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next: Status = await request();
        if (!cancelled) { setStatus(next); setDraft(old => old ?? next.settings); setError(null); }
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : "Status unavailable"); }
      if (!cancelled) timer = setTimeout(poll, 5000);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [revision]);

  const act = async (action: "save" | "load" | "unload") => {
    setBusy(true); setError(null);
    try {
      if (action === "save" && draft) await request("/settings", "PUT", draft);
      else await request(`/actions/${action}`, "POST");
      setRevision(n => n + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "Operation failed"); }
    finally { setBusy(false); }
  };

  const disabled = busy || !status?.can_manage || !status?.configured;
  const inputClass = "w-full min-w-0 border border-line bg-surf rounded p-2";
  const loaded = Boolean(status?.loaded_model);
  const selectedLoaded = Boolean(status?.selected_loaded);
  return <section aria-label="Session generation model management" className="min-w-0 space-y-4 rounded border border-line p-4 text-sm">
    <div className="flex items-center justify-between gap-4"><h2 className="text-lg">Session intelligence · brief + planning</h2><button type="button" className="text-xs text-mute hover:text-ember-text" onClick={() => setRevision(n => n + 1)}>Refresh</button></div>
    <p role="status">{status?.configured ? `LM Studio · ${loaded ? `loaded: ${status.loaded_model}` : "model not loaded"}` : (status ? "LM Studio management is not configured" : "Checking…")}</p>
    {status?.selected && <p className="text-mute">Selected: {status.selected.name}{status.selected.params_string ? ` · ${status.selected.params_string}` : ""}</p>}
    {status?.configured && status.can_manage && <div className="flex flex-wrap gap-2"><button type="button" disabled={disabled || selectedLoaded} onClick={() => void act("load")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Load selected model</button><button type="button" disabled={disabled || !loaded} onClick={() => void act("unload")} className="rounded border border-line px-3 py-2 disabled:opacity-40">Unload model</button></div>}
    {draft && status && <fieldset disabled={disabled} className="space-y-3 disabled:opacity-60"><legend className="mb-2">Session model settings</legend>
      <label className="block">Installed model<select className={inputClass} value={draft.model_key} onChange={e => setDraft({ ...draft, model_key: e.target.value })}>{!status.models.some(m => m.key === draft.model_key) && <option value={draft.model_key}>{draft.model_key} (not available)</option>}{status.models.filter(m => m.type === "llm" || m.type === "vlm").map(m => <option key={m.key} value={m.key}>{m.name}</option>)}</select></label>
      <label className="block">Context tokens<input className={inputClass} type="number" min={512} max={131072} step={512} value={draft.context_length} onChange={e => setDraft({ ...draft, context_length: Number(e.target.value) })} /></label>
      <label className="flex items-start gap-2"><input type="checkbox" checked={draft.flash_attention} onChange={e => setDraft({ ...draft, flash_attention: e.target.checked })} />Flash attention</label>
      <p className="text-mute">This model powers brief extraction and session planning. It is separate from Mind and ACE. Save settings, then load the model to apply them.</p>
      <button type="button" onClick={() => void act("save")} className="rounded border border-line px-3 py-2">Save settings</button>
    </fieldset>}
    {status && !status.can_manage && <p>Only administrators can manage session models.</p>}
    {(error || status?.error) && <p role="alert" className="text-warn">{error || status?.error}</p>}
  </section>;
}
