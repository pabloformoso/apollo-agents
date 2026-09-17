import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TrackPreparation } from "@/components/ember/TrackPreparation";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it.each(["queued", "running", "ready"])("shows persisted %s state", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status, error: null }))));
  render(<TrackPreparation trackId="techno--one" />);
  await waitFor(() => expect(screen.getByRole("status").textContent).not.toContain("Checking"));
  expect(screen.queryByRole("button")).toBeNull();
  expect(screen.getByRole("status").textContent).toContain(status === "ready" ? "ready" : status === "queued" ? "Queued" : "Preparing");
});

it("retries a failed track without publishing it again", async () => {
  const fetcher = vi.fn(async (_url, options?: RequestInit) => new Response(JSON.stringify({
    status: options?.method === "POST" ? "queued" : "failed", error: options?.method === "POST" ? null : "madmom unavailable",
  })));
  vi.stubGlobal("fetch", fetcher);
  render(<TrackPreparation trackId="techno--one" />);
  fireEvent.click(await screen.findByRole("button", { name: "Retry audio preparation" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/generator/tracks/techno--one/processing", expect.objectContaining({ method: "POST" })));
});

it("reports unavailable status without claiming the track is ready", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 503 })));
  render(<TrackPreparation trackId="one" />);
  expect((await screen.findByRole("alert")).textContent).toContain("Cannot read");
  expect(screen.queryByText("Audio ready for sessions.")).toBeNull();
});

it("shows permission errors on retry", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url, options?: RequestInit) => options?.method === "POST"
    ? new Response("", { status: 403 })
    : new Response(JSON.stringify({ status: "unprepared", error: null }))));
  render(<TrackPreparation trackId="old" />);
  fireEvent.click(await screen.findByRole("button", { name: "Prepare audio for sessions" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Only a catalog publisher");
});
