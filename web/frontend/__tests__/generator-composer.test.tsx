/**
 * The composer on /generations — describe a song where you will hear it.
 *
 * What is pinned: the form's body is the dialog's body (one definition,
 * `GeneratorForm`), the feed is handed a pending card the moment ACE
 * accepts the job, the card is re-read when the job lands, and the box
 * stays visible — inert, with the reason — when ACE is off.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ACE_OFF_REASON, GeneratorComposer } from "@/components/ember/GeneratorComposer";
import { GeneratorForm } from "@/components/ember/GeneratorForm";

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status < 400, status, statusText: status >= 400 ? "Error" : "OK", json: async () => body } as Response;
}

const GENRES = { genres: ["deep house", "techno"] };
const META = { genres: [{ id: "techno", bpm_default: 130, bpm_min: 120, bpm_max: 140, style_prompt: "driving techno" }] };
const DONE = {
  status: "done",
  takes: [{ index: 0, file: "/v1/audio?path=x", metas: { bpm: 130, duration: 180, keyscale: "A minor" } }],
};

function stubFetch(over: { health?: unknown; task?: unknown } = {}) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url.includes("/generator/health")) return jsonResponse(200, over.health ?? { available: true, blocked_by_live: false, stats: {} });
    if (url.includes("/generator/genres")) return jsonResponse(200, META);
    if (url.includes("/catalog")) return jsonResponse(200, GENRES);
    if (url.includes("/generator/tasks/")) return jsonResponse(200, over.task ?? DONE);
    if (url.includes("/generator/tasks")) return jsonResponse(200, { task_id: "t-1", queue_position: 0, eta_seconds: 42 });
    return jsonResponse(404, {});
  });
  vi.stubGlobal("fetch", fetcher);
  return calls;
}

beforeEach(() => {
  localStorage.setItem("apollo_token", "tok");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("GeneratorComposer", () => {
  it("submits the dialog's body, adopts the card, and re-reads it when the job lands", async () => {
    const calls = stubFetch();
    const onAdopt = vi.fn();
    const onLanded = vi.fn();
    render(<GeneratorComposer onAdopt={onAdopt} onLanded={onLanded} />);

    const genre = (await screen.findByTestId("generator-genre")) as HTMLSelectElement;
    await waitFor(() => expect(genre.options.length).toBeGreaterThan(1));
    fireEvent.change(genre, { target: { value: "techno" } });
    fireEvent.change(screen.getByTestId("generator-prompt"), { target: { value: "dark melodic techno, hypnotic" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("generator-submit"));
    });

    const post = calls.find((c) => c.url.endsWith("/generator/tasks") && c.init?.method === "POST");
    expect(post).toBeTruthy();
    const body = JSON.parse(String(post!.init!.body));
    expect(body).toMatchObject({
      prompt: "dark melodic techno, hypnotic",
      genre_folder: "techno",
      style_prompt: "driving techno",
      bpm: 130,
      audio_duration: 180,
      batch_size: 2,
    });
    expect(body.lyrics).toBeUndefined();

    await waitFor(() => expect(onAdopt).toHaveBeenCalledTimes(1));
    expect(onAdopt.mock.calls[0][0]).toMatchObject({ task_id: "t-1", eta_seconds: 42 });
    expect(onAdopt.mock.calls[0][1]).toMatchObject({ prompt: "dark melodic techno, hypnotic" });

    await waitFor(() => expect(onLanded).toHaveBeenCalledWith("t-1"));
    // Back to a ready box — the takes live in the card, not here — with the
    // words kept, so a tweak-and-regenerate is one edit away.
    await waitFor(() => expect(screen.queryByTestId("composer-pending")).toBeNull());
    expect((screen.getByTestId("generator-prompt") as HTMLTextAreaElement).disabled).toBe(false);
    expect((screen.getByTestId("generator-prompt") as HTMLTextAreaElement).value).toBe("dark melodic techno, hypnotic");
  });

  it("sends lyrics only when the box was opened and filled", async () => {
    const calls = stubFetch();
    render(<GeneratorComposer onAdopt={() => {}} onLanded={() => {}} />);
    const genre = (await screen.findByTestId("generator-genre")) as HTMLSelectElement;
    await waitFor(() => expect(genre.options.length).toBeGreaterThan(1));
    fireEvent.change(screen.getByTestId("generator-prompt"), { target: { value: "a song" } });
    expect(screen.queryByTestId("generator-lyrics")).toBeNull();
    fireEvent.click(screen.getByTestId("generator-lyrics-toggle"));
    fireEvent.change(screen.getByTestId("generator-lyrics"), { target: { value: "[Verse]\nrain" } });
    await act(async () => {
      fireEvent.click(screen.getByTestId("generator-submit"));
    });
    const post = calls.find((c) => c.init?.method === "POST");
    expect(JSON.parse(String(post!.init!.body)).lyrics).toBe("[Verse]\nrain");
  });

  it("says why Generate is grey until there is a description", async () => {
    stubFetch();
    render(<GeneratorComposer onAdopt={() => {}} onLanded={() => {}} />);
    const genre = (await screen.findByTestId("generator-genre")) as HTMLSelectElement;
    await waitFor(() => expect(genre.options.length).toBeGreaterThan(1));
    expect((screen.getByTestId("generator-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("generator-composer-hint").textContent).toBe("describe the song to generate");
    fireEvent.change(screen.getByTestId("generator-prompt"), { target: { value: "a song" } });
    expect(screen.queryByTestId("generator-composer-hint")).toBeNull();
    expect((screen.getByTestId("generator-submit") as HTMLButtonElement).disabled).toBe(false);
  });

  it("stays on screen, inert and explained, when ACE is off", async () => {
    stubFetch({ health: { available: false, blocked_by_live: false, stats: {} } });
    render(<GeneratorComposer onAdopt={() => {}} onLanded={() => {}} />);
    expect((await screen.findByTestId("generator-composer-disabled")).textContent).toContain(ACE_OFF_REASON);
    expect((screen.getByTestId("generator-prompt") as HTMLTextAreaElement).disabled).toBe(true);
  });
});

describe("GeneratorForm — the dialog's layout is unchanged", () => {
  it("renders the same fields and ids the dialog always had", async () => {
    stubFetch();
    render(<GeneratorForm active busy={false} onSubmit={() => {}} onCancel={() => {}} />);
    for (const id of ["generator-prompt", "generator-style", "generator-lyrics", "generator-duration", "generator-bpm", "generator-language", "generator-genre", "generator-batch", "generator-key-scale", "generator-time-signature", "generator-experimental-toggle", "generator-submit"]) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
    expect(screen.getByText("Cancel")).toBeTruthy();
  });
});
