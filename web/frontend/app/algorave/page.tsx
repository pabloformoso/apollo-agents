"use client";
/**
 * §11 S4 — `/algorave`, mounted CLIENT-ONLY.
 *
 * The surface has nothing to gain from a server render: it needs an
 * AudioContext, WebMIDI, CodeMirror and `localStorage`, none of which exist
 * there. What a server render DOES cost is a recurring class of bug — three
 * times in this lane a value that only the browser knows (the run id,
 * `midiSupport()`, now the saved session) could not be read during render
 * without a hydration mismatch, and each was worked around separately.
 *
 * `ssr: false` retires the whole class: state can be initialised from the
 * browser directly, in a lazy `useState`, with no effect and nothing to
 * reconcile. The cost is that this route stops prerendering, which for a page
 * that is blank until an AudioContext exists is not a cost.
 */
import dynamic from "next/dynamic";

const AlgoraveClient = dynamic(
  () => import("./AlgoraveClient").then((m) => m.AlgoraveClient),
  {
    ssr: false,
    loading: () => (
      <main className="min-h-screen bg-ink text-ember-text font-sans p-8">
        <p className="font-mono uppercase tracking-mono text-[10.5px] text-faint">
          loading the room…
        </p>
      </main>
    ),
  },
);

export default function AlgoravePage() {
  return <AlgoraveClient />;
}
