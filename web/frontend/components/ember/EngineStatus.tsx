"use client";
/**
 * What the two GPU tenants are holding, on the panel where you would act on it.
 *
 * **Why this exists.** The shared 16 GB is managed by a protocol nobody could
 * see: ACE wants ~12.5 GB and the live DJ's model ~6, so they cannot both be
 * resident — and every failure of that arrangement is silent. LM Studio answers
 * 400 for every model while still LISTING them; a first brief after an unload
 * simply takes a long time for no visible reason; an ACE left loaded holds the
 * GPU while nothing generates. Each of those cost hours before this panel.
 *
 * It reports what each box SAYS about itself and nothing else. In particular it
 * does not show free VRAM: neither server exposes it and `nvidia-smi` is not in
 * the backend's container, so any figure here would be an inference dressed as
 * a measurement.
 */
import { useCallback, useEffect, useState } from "react";
import { getEngineStatus, type EngineStatus as Status } from "@/lib/generator";

type Tone = "holding" | "idle" | "off";

const DOT: Record<Tone, string> = {
  holding: "bg-amber-400",
  idle: "bg-emerald-500",
  off: "bg-faint",
};

function Row({
  label, tone, headline, detail,
}: {
  label: string; tone: Tone; headline: string; detail?: string;
}) {
  return (
    <li className="flex items-baseline gap-2">
      <span className={`mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full ${DOT[tone]}`} />
      <span className="font-mono uppercase tracking-mono text-[10px] text-faint w-14 shrink-0">
        {label}
      </span>
      <span className="font-mono text-[11px] text-ember-text">{headline}</span>
      {detail && <span className="font-mono text-[10px] text-faint truncate">{detail}</span>}
    </li>
  );
}

/** Pure: the status → what a performer needs to read. Tested without a DOM. */
export function readAce(s: Status["ace"]): { tone: Tone; headline: string; detail?: string } {
  if (!s.configured) return { tone: "off", headline: "not configured" };
  if (!s.reachable) return { tone: "off", headline: "not answering" };
  if (s.loaded) {
    return {
      tone: "holding",
      headline: "holding the GPU",
      detail: [s.model, s.lm_model].filter(Boolean).join(" + ") || undefined,
    };
  }
  // The intended resting state: up, weighing nothing, loads on first job.
  return { tone: "idle", headline: "ready, holding nothing", detail: s.model ?? undefined };
}

export function readLlm(s: Status["llm"]): { tone: Tone; headline: string; detail?: string } {
  if (!s.configured) return { tone: "off", headline: "not configured" };
  if (!s.reachable) return { tone: "off", headline: "not answering" };
  if (s.loaded.length === 0) {
    // Not a fault: it loads on demand. But it explains a slow first brief,
    // which read as a bug until this line existed.
    return { tone: "idle", headline: "no model loaded", detail: `${s.known} available` };
  }
  return { tone: "holding", headline: "holding the GPU", detail: s.loaded.join(", ") };
}

export function EngineStatusPanel() {
  const [status, setStatus] = useState<Status | null>(null);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getEngineStatus());
      setFailed(false);
    } catch {
      // A status panel must never be the thing that breaks the page.
      setFailed(true);
    }
  }, []);

  // Read once on mount. Written as a promise callback rather than
  // `void refresh()` so the state lands OUTSIDE the effect body — the
  // `set-state-in-effect` rule, and the same shape `AlgoraveClient` uses for
  // its model list. The cancelled flag keeps a slow answer from a closed
  // dialog out of a component that is gone.
  useEffect(() => {
    let cancelled = false;
    getEngineStatus().then(
      (s) => { if (!cancelled) setStatus(s); },
      () => { if (!cancelled) setFailed(true); },
    );
    return () => { cancelled = true; };
  }, []);

  if (failed || !status) return null;

  const ace = readAce(status.ace);
  const llm = readLlm(status.llm);

  return (
    <section
      data-testid="engine-status"
      className="border border-line rounded p-2 flex flex-col gap-1"
    >
      <div className="flex items-center justify-between">
        <span className="font-mono uppercase tracking-mono text-[10px] text-faint">
          shared GPU
        </span>
        <button
          type="button"
          onClick={() => void refresh()}
          className="font-mono text-[10px] text-faint hover:text-ember-text"
        >
          refresh
        </button>
      </div>
      <ul className="flex flex-col gap-0.5">
        <Row label="ACE" {...ace} />
        <Row label="DJ / LLM" {...llm} />
      </ul>
      {status.ace.loaded && status.llm.loaded.length > 0 && (
        <p className="font-mono text-[10px] text-amber-400">
          Both resident — they do not fit in 16 GB together.
        </p>
      )}
      {status.blocked_by_live && (
        <p className="font-mono text-[10px] text-faint">
          A set is on air: generation is refused until it ends.
        </p>
      )}
    </section>
  );
}
