"use client";
/**
 * §11 S3 — the Strudel bundle spike. THROWAWAY.
 *
 * This route exists to answer one question before any design work happens:
 * can a Next route run Strudel with exactly one `Pattern` class, in a
 * production build and not just `next dev`?
 *
 * The risk it probes (see the comment in next.config.ts): `@strudel/web`'s
 * dist is a self-contained bundle, but the package declares the sub-packages
 * as dependencies, so they also sit in node_modules with their own builds.
 * Two `Pattern` classes means patterns built by one are not recognised by the
 * other — and that failure is SILENT. No error, no audio. A spinner that
 * never resolves is what you would actually see.
 *
 * S4 replaces this page with the real `/algorave`. The identity assertion
 * below should survive that move — it is the regression guard.
 */
import { useCallback, useEffect, useState } from "react";

type Check = { ok: boolean; detail: string };

const PATTERN = `stack(
  s("bd*4").bank("RolandTR909").gain(0.9),
  s("~ cp").bank("RolandTR909").room(0.3),
  s("hh*8").bank("RolandTR909").gain(0.4),
  note("c2 eb2 g2 bb2").s("supersaw").lpf(sine.range(400, 2000).slow(8)).gain(0.5)
).cpm(124/4)`;

export default function StrudelSpikePage() {
  const [identity, setIdentity] = useState<Check | null>(null);
  const [audio, setAudio] = useState<string>("idle");
  const [playing, setPlaying] = useState(false);

  // The invariant, checked at runtime in the browser that will actually run
  // it. `@strudel/core` is aliased to the same file as `@strudel/web`, so the
  // two specifiers must yield the identical class object. Drop the alias from
  // next.config.ts and this flips to FAIL — that is the point of it.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [web, core] = await Promise.all([
          import("@strudel/web"),
          import("@strudel/core"),
        ]);
        if (cancelled) return;
        const a = web.Pattern;
        const b = core.Pattern;
        const ok = typeof a === "function" && a === b;
        setIdentity({
          ok,
          detail: ok
            ? "@strudel/web and @strudel/core resolve to the SAME Pattern class."
            : `MISMATCH — web:${typeof a} core:${typeof b}. Two Pattern classes: ` +
              "patterns built by one will be silently ignored by the other.",
        });
      } catch (err) {
        if (!cancelled) {
          setIdentity({ ok: false, detail: `import failed: ${String(err)}` });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // initStrudel needs a user gesture — an AudioContext started without one is
  // created suspended and stays silent.
  const play = useCallback(async () => {
    try {
      setAudio("loading engine…");
      const strudel = await import("@strudel/web");
      await strudel.initStrudel();
      setAudio("evaluating…");
      await strudel.evaluate(PATTERN);
      setPlaying(true);
      setAudio("playing — you should HEAR a 909 pattern with a supersaw bass");
    } catch (err) {
      setAudio(`FAILED: ${String(err)}`);
    }
  }, []);

  const stop = useCallback(async () => {
    const strudel = await import("@strudel/web");
    strudel.hush();
    setPlaying(false);
    setAudio("stopped");
  }, []);

  return (
    <main className="min-h-screen bg-ink text-ember-text p-8 font-sans">
      <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
        §11 S3 · spike · throwaway
      </p>
      <h1 className="font-display italic text-4xl tracking-display-tight mt-1 mb-6">
        Strudel in Next
      </h1>

      <section
        data-testid="identity-check"
        data-ok={identity ? String(identity.ok) : "pending"}
        className="border border-line rounded-md bg-surf p-4 mb-4 max-w-3xl"
      >
        <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint mb-2">
          One Pattern class
        </p>
        {identity === null ? (
          <p className="text-mute">checking…</p>
        ) : (
          <p className={identity.ok ? "text-ok" : "text-ember"}>
            {identity.ok ? "PASS — " : "FAIL — "}
            {identity.detail}
          </p>
        )}
      </section>

      <section className="border border-line rounded-md bg-surf p-4 max-w-3xl">
        <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint mb-3">
          Audio
        </p>
        <div className="flex gap-3 mb-3">
          <button
            type="button"
            onClick={play}
            disabled={playing}
            data-testid="play"
            className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded bg-ember text-ink disabled:opacity-40"
          >
            Play
          </button>
          <button
            type="button"
            onClick={stop}
            disabled={!playing}
            data-testid="stop"
            className="font-mono uppercase tracking-mono text-[10.5px] px-4 py-2 rounded border border-line2 disabled:opacity-40"
          >
            Stop
          </button>
        </div>
        <p data-testid="audio-status" className="text-mute text-sm">
          {audio}
        </p>
        <pre className="mt-4 text-xs font-mono text-faint overflow-x-auto">{PATTERN}</pre>
      </section>
    </main>
  );
}
