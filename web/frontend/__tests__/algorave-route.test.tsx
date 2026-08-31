/**
 * §11 S4 — the shared stage modes and the run identity.
 *
 * The switcher and its hash sync are seam 3 of §11.3: `/live` and `/algorave`
 * must render the SAME control, so these tests pin the contract both consume
 * rather than either page's layout. The run id is seam 5 — a rave run gets an
 * identity from day one so the later fusion is a composition, not a migration.
 */
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import * as React from "react";

import {
  ModeSwitcher,
  STAGE_MODES,
  isStageMode,
  useStageMode,
  type StageMode,
} from "@/components/ember/ModeSwitcher";
import { RUN_PARAM, newRunId, resolveRunId } from "@/lib/algorave-run";
import { TurnStrip } from "@/components/ember/TurnStrip";

afterEach(() => {
  cleanup();
  window.location.hash = "";
  window.history.replaceState(null, "", "/");
});

describe("stage modes — the vocabulary both surfaces share", () => {
  it("keeps the three modes, in order, with `cabin` spelled as the code has always spelled it", () => {
    // Renaming `cabin` to `booth` would break every existing URL hash,
    // bookmark and OBS Browser Source. The label is Booth; the id is not.
    expect(STAGE_MODES.map(([id]) => id)).toEqual([
      "audience",
      "cabin",
      "immersive",
    ]);
    expect(STAGE_MODES.map(([, label]) => label)).toEqual([
      "Audience",
      "Booth",
      "Immersive",
    ]);
  });

  it("guards unknown hashes", () => {
    expect(isStageMode("cabin")).toBe(true);
    expect(isStageMode("booth")).toBe(false);
    expect(isStageMode("")).toBe(false);
  });
});

function Harness({ initial }: { initial?: StageMode }) {
  const [mode, setMode] = useStageMode(initial);
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <ModeSwitcher mode={mode} onChange={setMode} />
    </div>
  );
}

describe("useStageMode — the hash is the memory", () => {
  it("adopts a valid mode from the hash on mount", () => {
    window.location.hash = "#immersive";
    render(<Harness />);
    expect(screen.getByTestId("mode").textContent).toBe("immersive");
  });

  it("ignores a hash that is not a mode, keeping the caller's default", () => {
    window.location.hash = "#nonsense";
    render(<Harness initial="cabin" />);
    expect(screen.getByTestId("mode").textContent).toBe("cabin");
  });

  it("writes the mode back to the hash so a reload lands where the user was", () => {
    render(<Harness initial="audience" />);
    act(() => {
      screen.getByText("Booth").click();
    });
    expect(screen.getByTestId("mode").textContent).toBe("cabin");
    expect(window.location.hash).toBe("#cabin");
  });

  it("replaces rather than pushes — flipping modes must not fill the back button", () => {
    const before = window.history.length;
    render(<Harness initial="audience" />);
    act(() => {
      screen.getByText("Immersive").click();
    });
    act(() => {
      screen.getByText("Booth").click();
    });
    expect(window.history.length).toBe(before);
  });
});

describe("run identity (§11.3 seam 5)", () => {
  it("mints an id without crypto.randomUUID — the API a non-secure origin withholds", () => {
    const original = globalThis.crypto;
    // Same constraint that costs us AudioWorklet over plain HTTP: a run id is
    // not a security token, so it must degrade rather than throw.
    Object.defineProperty(globalThis, "crypto", {
      value: {},
      configurable: true,
    });
    try {
      const id = newRunId();
      expect(id).toMatch(/^[a-z0-9]+$/);
      expect(id.length).toBeGreaterThan(4);
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        value: original,
        configurable: true,
      });
    }
  });

  it("puts a fresh id in the URL, and reuses the one already there", () => {
    const first = resolveRunId();
    expect(new URL(window.location.href).searchParams.get(RUN_PARAM)).toBe(
      first,
    );
    // A reload, a second tab, or S8's read-only view must name the same run.
    expect(resolveRunId()).toBe(first);
  });

  it("does not add a history entry — arriving is one navigation, not two", () => {
    const before = window.history.length;
    resolveRunId();
    expect(window.history.length).toBe(before);
  });
});

describe("TurnStrip — seam 4, mountable over any instrument", () => {
  it("names who holds the pen and offers to take it back", () => {
    render(
      <TurnStrip
        pen="mind"
        barsNow={12}
        phraseBars={8}
        nextBoundaryBar={16}
        barsToFlip={null}
        onTogglePen={() => {}}
      />,
    );
    expect(screen.getByTestId("turn-strip").dataset.pen).toBe("mind");
    expect(screen.getByTestId("pen-holder").textContent).toBe("Mind");
    expect(screen.getByTestId("toggle-pen").textContent).toContain("take the pen back");
    expect(screen.getByTestId("next-boundary").textContent).toContain("bar 16");
  });

  it("shows the WHY — an idle mind and a busy one are different silences", () => {
    render(
      <TurnStrip
        pen="mind"
        barsNow={8}
        phraseBars={8}
        nextBoundaryBar={16}
        barsToFlip={null}
        why="request-in-flight"
      />,
    );
    expect(screen.getByTestId("turn-why").textContent).toBe("request-in-flight");
  });

  it("hides the flip counter when not alternating, and shows it when it is", () => {
    const { rerender } = render(
      <TurnStrip pen="human" barsNow={4} phraseBars={8} nextBoundaryBar={8} barsToFlip={null} />,
    );
    expect(screen.queryByTestId("bars-to-flip")).toBeNull();
    rerender(
      <TurnStrip pen="human" barsNow={4} phraseBars={8} nextBoundaryBar={8} barsToFlip={12} />,
    );
    expect(screen.getByTestId("bars-to-flip").textContent).toContain("12");
  });

  it("renders from a DECK-shaped prop set — no Strudel anywhere near it", () => {
    // §11.3 seam 4: a crossfade IS a phrase boundary, so this component must be
    // mountable over the DJ lane unchanged. Nothing here mentions a buffer, a
    // pattern or a sound: bars, a pen and a reason are the whole vocabulary.
    render(
      <TurnStrip
        pen="human"
        barsNow={64}
        phraseBars={32}
        nextBoundaryBar={96}
        barsToFlip={32}
        working="crossfade into Velvet Corridor"
        why="between-boundaries"
      />,
    );
    expect(screen.getByTestId("turn-working").textContent).toContain(
      "crossfade into Velvet Corridor",
    );
    expect(screen.getByTestId("pen-holder").textContent).toBe("You");
  });
});
