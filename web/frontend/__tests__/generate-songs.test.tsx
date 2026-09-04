/**
 * The catalog's door to ACE.
 *
 * The rule with teeth is the ABSENCE one: the ACE box is off most of the time
 * by design, and a button that offers generation when nothing can generate is
 * a promise the app cannot keep. Absent is the normal look, not an error —
 * the same rule the editor's tile follows.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { GenerateSongs } from "@/components/ember/GenerateSongs";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function healthAnswers(body: unknown, ok = true) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(body), { status: ok ? 200 : 503 })),
  );
}

describe("GenerateSongs", () => {
  it("offers the door when ACE is available", async () => {
    healthAnswers({ available: true, blocked_by_live: false, stats: null });
    render(<GenerateSongs />);
    await waitFor(() =>
      expect(screen.getByTestId("generate-songs")).toBeTruthy(),
    );
  });

  it("renders NOTHING when ACE is unavailable", async () => {
    // Not a disabled button, not an error: nothing. The box being off is the
    // ordinary state of this machine.
    healthAnswers({ available: false, blocked_by_live: false, stats: null });
    render(<GenerateSongs />);
    await waitFor(() => {
      expect(screen.queryByTestId("generate-songs")).toBeNull();
    });
  });

  it("renders nothing while the answer is still in flight", () => {
    // No flicker: it must not appear and then vanish.
    healthAnswers({ available: true, blocked_by_live: false, stats: null });
    render(<GenerateSongs />);
    expect(screen.queryByTestId("generate-songs")).toBeNull();
  });

  it("disables it while a set is on air rather than hiding it", async () => {
    // Different from unavailable: the box is there, the GPU is busy. Hiding it
    // would read as "the feature is gone" instead of "not right now", and the
    // POST would refuse with a 409 anyway.
    healthAnswers({ available: true, blocked_by_live: true, stats: null });
    render(<GenerateSongs />);
    await waitFor(() =>
      expect(
        screen.getByTestId("generate-songs").hasAttribute("disabled"),
      ).toBe(true),
    );
  });

  it("survives a health endpoint that fails outright", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<GenerateSongs />);
    await waitFor(() => {
      expect(screen.queryByTestId("generate-songs")).toBeNull();
    });
  });
});
