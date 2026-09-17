import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AceServicePanel } from "@/components/ember/AceServicePanel";
import { useGeneratorHealth, type AceServiceStatus } from "@/lib/generator";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const base: AceServiceStatus = {
  configured: true, reachable: true, can_manage: true, blocked_by_live: false,
  state: "stopped", ready: false, loaded: false, queued: null, running: null,
  pending_results: 0, reason: null,
};

function answer(status: Partial<AceServiceStatus> = {}) {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ ...base, ...status })));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

describe("ACE service panel", () => {
  it("lets an admin start an offline generator", async () => {
    const fetcher = answer();
    render(<AceServicePanel />);
    const start = await screen.findByRole("button", { name: "Start ACE" });
    expect(start.hasAttribute("disabled")).toBe(false);
    expect(screen.getByRole("button", { name: "Stop ACE" }).hasAttribute("disabled")).toBe(true);
    fireEvent.click(start);
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      "/api/generator/service/start", expect.objectContaining({ method: "POST" }),
    ));
  });

  it("does not offer lifecycle commands to listeners", async () => {
    answer({ can_manage: false });
    render(<AceServicePanel />);
    await screen.findByText("An administrator can start or stop ACE.");
    expect(screen.queryByRole("button", { name: "Start ACE" })).toBeNull();
  });

  it.each([
    { state: "unknown", reachable: false },
    { state: "running", queued: null, running: null },
    { state: "running", queued: 1, running: 0 },
    { state: "running", queued: 0, running: 1 },
    { state: "running", queued: 0, running: 0, pending_results: 1 },
    { state: "stopped", blocked_by_live: true },
  ] as Partial<AceServiceStatus>[])("disables unsafe controls: %j", async (state) => {
    answer(state);
    render(<AceServicePanel />);
    await screen.findByRole("button", { name: "Stop ACE" });
    expect(screen.getByRole("button", { name: "Stop ACE" }).hasAttribute("disabled")).toBe(true);
    expect(screen.getByRole("button", { name: "Start ACE" }).hasAttribute("disabled")).toBe(true);
  });

  it("stops an idle service and shows refusals verbatim", async () => {
    const fetcher = answer({ state: "running", ready: true, queued: 0, running: 0 });
    render(<AceServicePanel />);
    const stop = await screen.findByRole("button", { name: "Stop ACE" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fetcher.mockImplementationOnce(async () => new Response(
      JSON.stringify({ detail: "ACE has queued or running jobs." }), { status: 409 },
    ));
    fireEvent.click(stop);
    expect((await screen.findByRole("alert")).textContent).toBe("ACE has queued or running jobs.");
  });

  it("keeps a recovery action when the status request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("Network unavailable"); }));
    render(<AceServicePanel />);
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start ACE" })).toBeNull();
  });

  it("refreshes generation availability after service state changes", async () => {
    let available = false;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ available, blocked_by_live: false, stats: null }))));
    function Availability() {
      const state = useGeneratorHealth();
      return <p>{state.status}</p>;
    }
    render(<Availability />);
    await screen.findByText("unavailable");
    available = true;
    window.dispatchEvent(new Event("apollo-generator-status"));
    await screen.findByText("ready");
  });
});
