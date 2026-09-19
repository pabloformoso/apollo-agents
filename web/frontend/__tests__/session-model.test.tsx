import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SessionModelPanel } from "@/components/ember/SessionModelPanel";

const status = {
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

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Session model management", () => {
  it("loads the model currently selected in the form", async () => {
    localStorage.setItem("apollo_token", "test-token");
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => status });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionModelPanel />);

    const select = await screen.findByLabelText("Installed model");
    fireEvent.change(select, { target: { value: "model-b" } });
    fireEvent.click(screen.getByText("Load selected model"));

    await waitFor(() => expect(fetcher).toHaveBeenCalledWith(
      "/api/session-model/actions/load",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ Authorization: "Bearer test-token" }),
        body: JSON.stringify({ model_key: "model-b", context_length: 4096, flash_attention: true }),
      }),
    ));
  });
});
