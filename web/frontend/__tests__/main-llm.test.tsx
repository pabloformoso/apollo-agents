import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MainLlmPanel } from "@/components/ember/MainLlmPanel";

const llmStatus = {
  configured: true,
  provider: "ollama",
  endpoint: "http://lmstudio:1234",
  settings: { model_key: "model-a", context_length: 4096, flash_attention: true },
  models: [
    { key: "model-a", name: "Model A", type: "llm", state: "not-loaded", loaded_instances: [], max_context_length: 8192 },
    { key: "model-b", name: "Model B", type: "llm", state: "not-loaded", loaded_instances: [], max_context_length: 8192 },
  ],
  selected: { key: "model-a", name: "Model A", type: "llm", state: "not-loaded", loaded_instances: [] },
  loaded_model: null,
  selected_loaded: false,
  can_manage: true,
  error: null,
};

const mindStatus = { service: "inactive", reachable: false, loaded_models: [], busy: false, operation: null, error: null, uncertain: false, can_manage: true, main_llm: "model-a" };

/** One fetch for both routes: the panel is the one place both are read. */
function stubFetch(mind: unknown = mindStatus, mindOk = true) {
  const fetcher = vi.fn(async (url: string) => {
    if (url.startsWith("/api/mind")) return { ok: mindOk, json: async () => mind };
    return { ok: true, json: async () => llmStatus };
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Main LLM management", () => {
  it("loads the model currently selected in the form", async () => {
    localStorage.setItem("apollo_token", "test-token");
    const fetcher = stubFetch();
    render(<MainLlmPanel />);

    const select = await screen.findByLabelText("Installed model");
    fireEvent.change(select, { target: { value: "model-b" } });
    fireEvent.click(screen.getByText("Load selected model"));

    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      "/api/main-llm/actions/load",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer test-token" }),
        body: JSON.stringify({ model_key: "model-b", context_length: 4096, flash_attention: true }),
      }),
    ));
  });

  it("starts the Mind service without loading anything", async () => {
    localStorage.setItem("apollo_token", "test-token");
    const fetcher = stubFetch();
    render(<MainLlmPanel />);

    await screen.findByText("Service: inactive");
    fireEvent.click(screen.getByText("Start Mind"));

    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      "/api/mind/actions/start",
      expect.objectContaining({ method: "POST", headers: expect.objectContaining({ Authorization: "Bearer test-token" }) }),
    ));
    expect(fetcher.mock.calls.some(c => String(c[0]).endsWith("/load"))).toBe(false);
    // The Mind has no model routes of its own any more.
    expect(fetcher.mock.calls.every(c => !String(c[0]).startsWith("/api/mind/settings"))).toBe(true);
  });

  it("keeps managing the model when the Mind host controller is not configured", async () => {
    stubFetch({ detail: "Mind host controller is not configured." }, false);
    render(<MainLlmPanel />);

    await screen.findByLabelText("Installed model");
    expect(screen.getByText("Host controller not configured")).toBeTruthy();
    expect(screen.queryByText("Start Mind")).toBeNull();
    expect((screen.getByText("Load selected model") as HTMLButtonElement).disabled).toBe(false);
  });

  it("disables both Mind actions while an answer is in flight", async () => {
    stubFetch({ ...mindStatus, service: "active", busy: true, operation: "inference" });
    render(<MainLlmPanel />);
    await screen.findByText("Stop Mind");
    expect((screen.getByText("Stop Mind") as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByText("Start Mind") as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps Stop available while a transport is unresolved: stopping is what resolves it", async () => {
    stubFetch({ ...mindStatus, service: "active", uncertain: true });
    render(<MainLlmPanel />);
    await screen.findByText("Stop Mind");
    expect((screen.getByText("Stop Mind") as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByText("Start Mind") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("alert").textContent).toContain("Stop Mind");
  });
});
