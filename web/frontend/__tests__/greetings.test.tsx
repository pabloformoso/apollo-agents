/**
 * Vitest coverage for the v3.7.0 greeting overlay: the pure queue logic
 * in lib/greetings.ts and the GreetingOverlay timing component.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import React from "react";

import {
  COALESCE_THRESHOLD,
  Greeting,
  TOAST_DURATION_MS,
  TOAST_GAP_MS,
  nextToast,
} from "@/lib/greetings";
import GreetingOverlay from "@/components/GreetingOverlay";

let seq = 0;
function g(author: string, kind: Greeting["kind"] = "first"): Greeting {
  seq += 1;
  return { id: seq, author, kind, ts: 1_000 };
}

describe("nextToast (pure queue logic)", () => {
  it("returns null on an empty queue", () => {
    expect(nextToast([])).toBeNull();
  });

  it("greets a single chatter individually, consuming one entry", () => {
    const plan = nextToast([g("marta")]);
    expect(plan).not.toBeNull();
    expect(plan!.consumed).toBe(1);
    expect(plan!.text).toContain("@marta");
  });

  it("greets two waiting chatters one by one (below threshold)", () => {
    const plan = nextToast([g("a"), g("b")]);
    expect(plan!.consumed).toBe(1);
    expect(plan!.text).toContain("@a");
  });

  it("coalesces a burst into one collective toast consuming the queue", () => {
    const queue = [g("a"), g("b"), g("c"), g("d"), g("e")];
    expect(queue.length).toBeGreaterThanOrEqual(COALESCE_THRESHOLD);
    const plan = nextToast(queue);
    expect(plan!.consumed).toBe(5);
    expect(plan!.text).toContain("@a");
    expect(plan!.text).toContain("@b");
    expect(plan!.text).toContain("@c");
    expect(plan!.text).toContain("y 2 más");
    expect(plan!.text).not.toContain("@d");
  });

  it("collective toast with exactly the threshold lists all names, no tail", () => {
    const plan = nextToast([g("a"), g("b"), g("c")]);
    expect(plan!.consumed).toBe(3);
    expect(plan!.text).toContain("@c");
    expect(plan!.text).not.toContain("más");
  });

  it("is deterministic per author (template pool keyed by name)", () => {
    const a1 = nextToast([g("marta")])!.text;
    const a2 = nextToast([g("marta")])!.text;
    expect(a1).toBe(a2);
  });

  it("returning chatters get the welcome-back line", () => {
    const plan = nextToast([g("marta", "returning")]);
    expect(plan!.text).toContain("de vuelta");
  });
});

describe("GreetingOverlay (timing component)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    seq = 0;
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders nothing with an empty feed", () => {
    render(<GreetingOverlay greetings={[]} />);
    expect(screen.queryByTestId("greeting-toast")).toBeNull();
  });

  it("shows a toast for a new greeting and hides it after the duration", async () => {
    const { rerender } = render(<GreetingOverlay greetings={[]} />);
    rerender(<GreetingOverlay greetings={[g("marta")]} />);
    // Ingest kick is a setTimeout(0).
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByTestId("greeting-toast").textContent).toContain(
      "@marta",
    );
    await act(async () => {
      vi.advanceTimersByTime(TOAST_DURATION_MS + 10);
    });
    expect(screen.queryByTestId("greeting-toast")).toBeNull();
  });

  it("paces two greetings: second toast only after duration + gap", async () => {
    const first = g("uno");
    const second = g("dos");
    const { rerender } = render(<GreetingOverlay greetings={[]} />);
    rerender(<GreetingOverlay greetings={[first, second]} />);
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByTestId("greeting-toast").textContent).toContain("@uno");
    // Mid-display: still the first toast, not replaced.
    await act(async () => {
      vi.advanceTimersByTime(TOAST_DURATION_MS / 2);
    });
    expect(screen.getByTestId("greeting-toast").textContent).toContain("@uno");
    // After duration + gap: second toast.
    await act(async () => {
      vi.advanceTimersByTime(TOAST_DURATION_MS / 2 + TOAST_GAP_MS + 20);
    });
    expect(screen.getByTestId("greeting-toast").textContent).toContain("@dos");
  });

  it("does not re-show already-consumed greetings on rerender", async () => {
    const only = g("marta");
    const { rerender } = render(<GreetingOverlay greetings={[only]} />);
    await act(async () => {
      vi.advanceTimersByTime(10);
    });
    expect(screen.getByTestId("greeting-toast")).toBeTruthy();
    await act(async () => {
      vi.advanceTimersByTime(TOAST_DURATION_MS + TOAST_GAP_MS + 20);
    });
    expect(screen.queryByTestId("greeting-toast")).toBeNull();
    // Same feed re-rendered (parent state unchanged) → no zombie toast.
    rerender(<GreetingOverlay greetings={[only]} />);
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.queryByTestId("greeting-toast")).toBeNull();
  });
});
