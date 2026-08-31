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
