/**
 * §11 S8 — the viewer gate and the run mirror.
 *
 * The gate's three states are the whole point (v3.6.2): a `?viewer=1` page that
 * treats "not yet resolved" as "operator" attaches to the primary endpoint,
 * displaces the operator and kills the session on teardown — an OBS Browser
 * Source that silently ends the set it is mirroring.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import * as React from "react";
import { VIEWER_PARAM, useViewerFlag, viewerUrlFor } from "@/lib/viewer";
import { fetchRun, publishRun, readRunId, resolveRunId } from "@/lib/algorave-run";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

function Gate() {
  const { flag, isViewer, resolved } = useViewerFlag();
  return (
    <span data-testid="gate" data-flag={String(flag)} data-viewer={String(isViewer)}>
      {resolved ? "resolved" : "pending"}
    </span>
  );
}

describe("the viewer gate is three-state, and that matters", () => {
  it("reports an operator page as not-a-viewer once resolved", async () => {
    window.history.replaceState(null, "", "/algorave");
    render(<Gate />);
    await waitFor(() =>
      expect(screen.getByTestId("gate").textContent).toBe("resolved"),
    );
    expect(screen.getByTestId("gate").dataset.viewer).toBe("false");
  });

  it("reports ?viewer=1 as a viewer", async () => {
    window.history.replaceState(null, "", "/algorave?viewer=1");
    render(<Gate />);
    await waitFor(() =>
      expect(screen.getByTestId("gate").dataset.viewer).toBe("true"),
    );
  });

  it("never reports `true` for anything but the exact flag", async () => {
    // `?viewer=yes` or `?viewer=0` is someone hand-editing a URL; only "1" is
    // the contract `/live` has always used and OBS sources already carry.
    for (const q of ["?viewer=0", "?viewer=yes", "?viewer="]) {
      cleanup();
      window.history.replaceState(null, "", `/algorave${q}`);
      render(<Gate />);
      await waitFor(() =>
        expect(screen.getByTestId("gate").textContent).toBe("resolved"),
      );
      expect(screen.getByTestId("gate").dataset.viewer).toBe("false");
    }
  });
});

describe("viewerUrlFor", () => {
  it("keeps the run id — the mirror must name the SAME run", () => {
    const url = viewerUrlFor("https://host:4443/algorave?run=abc123#cabin");
    expect(new URL(url).searchParams.get("run")).toBe("abc123");
    expect(new URL(url).searchParams.get(VIEWER_PARAM)).toBe("1");
  });

  it("is idempotent, so copying twice does not produce ?viewer=1&viewer=1", () => {
    const once = viewerUrlFor("https://host/algorave?run=a");
    expect(viewerUrlFor(once)).toBe(once);
  });
});

describe("run id: the viewer reads, the operator mints", () => {
  it("readRunId does NOT mint — a minted id is one nobody publishes under", () => {
    window.history.replaceState(null, "", "/algorave?viewer=1");
    expect(readRunId()).toBeNull();
    // And the URL is untouched: a viewer must not rewrite what OBS was given.
    expect(window.location.search).toBe("?viewer=1");
  });

  it("resolveRunId mints for the operator and readRunId then finds it", () => {
    window.history.replaceState(null, "", "/algorave");
    const id = resolveRunId();
    expect(readRunId()).toBe(id);
  });
});

describe("the run mirror", () => {
  it("publishes to the run's own endpoint — id in the QUERY, not the path", async () => {
    // A path segment would be a dynamic route, and `afterFiles` rewrites are
    // checked before those: `/api/:path*` would swallow it and proxy to :4020.
    // See app/api/algorave/run/route.ts.
    const fetchSpy = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchSpy);
    await publishRun("run-1", {
      buffer: 's("bd*4")',
      pen: "mind",
      barsNow: 8,
      phraseBars: 8,
      reason: "sparser",
    });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/algorave/run?id=run-1");
    expect(JSON.parse(String(init.body)).pen).toBe("mind");
  });

  it("swallows a failed publish — a mirror must never interrupt a performance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await expect(
      publishRun("run-1", {
        buffer: "x", pen: "human", barsNow: 0, phraseBars: 8, reason: "",
      }),
    ).resolves.toBeUndefined();
  });

  it("reads `waiting` as 'nobody has played yet', not as an error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ waiting: true }), { status: 200 }),
    ));
    expect(await fetchRun("run-1")).toBeNull();
  });

  it("returns the snapshot the operator published", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(
        JSON.stringify({ buffer: 's("cp")', pen: "mind", barsNow: 16, phraseBars: 4, reason: "r" }),
        { status: 200 },
      ),
    ));
    expect(await fetchRun("run-1")).toEqual({
      buffer: 's("cp")', pen: "mind", barsNow: 16, phraseBars: 4, reason: "r",
    });
  });
});
