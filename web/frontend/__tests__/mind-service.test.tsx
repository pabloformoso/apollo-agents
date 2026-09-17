import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MindServicePanel } from "@/components/ember/MindServicePanel";

const status = { service: "inactive", reachable: false, model_loaded: false, models: [{ key: "gemma", name: "Gemma" }], settings: { model_key: "gemma", context_length: 4096, gpu_fraction: 0.25, allow_shared_gpu: false }, busy: false, uncertain: false, can_manage: true };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe("Mind management", () => {
  it("separates service actions from loading and sends authenticated commands", async () => {
    localStorage.setItem("apollo_token", "test-token");
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    vi.stubGlobal("fetch", fetcher);
    render(<MindServicePanel />);
    await screen.findByText("Service: inactive · Model: unloaded");
    fireEvent.click(screen.getByText("Start Mind"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/mind/actions/start", expect.objectContaining({ method: "POST", headers: expect.objectContaining({ Authorization: "Bearer test-token" }) })));
    expect(fetcher.mock.calls.some(c => c[0].endsWith("/load"))).toBe(false);
  });
  it("saves coexistence explicitly without loading a model", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    vi.stubGlobal("fetch", fetcher);
    render(<MindServicePanel />);
    fireEvent.click(await screen.findByLabelText("Allow Mind and ACE to coexist"));
    expect(fetcher.mock.calls).toHaveLength(1);
    fireEvent.click(screen.getByText("Save settings"));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/mind/settings", expect.objectContaining({ method: "PUT", body: JSON.stringify({ ...status.settings, allow_shared_gpu: true }) })));
  });
  it.each([{ can_manage: false }, { busy: true }, { uncertain: true }])("disables actions when unsafe: %s", async override => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ...status, ...override }) }));
    render(<MindServicePanel />);
    await screen.findByLabelText("Installed model");
    expect((screen.getByText("Start Mind") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText("Load model") as HTMLButtonElement).disabled).toBe(true);
  });
});
