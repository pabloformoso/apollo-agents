import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PlayerProvider, usePlayer } from "@/lib/player";
import { CatalogPlayer } from "@/components/ember/CatalogPlayer";
import type { Track } from "@/lib/types";

const live = vi.hoisted(() => ({ active: false }));
vi.mock("@/lib/live", () => ({ useIsLiveActive: () => live.active }));
let audio: FakeAudio;
class FakeAudio extends EventTarget {
  src = "";
  currentTime = 0;
  duration = 180;
  paused = true;
  volume = 1;
  preload = "";
  play = vi.fn(async () => { this.paused = false; this.dispatchEvent(new Event("play")); });
  pause() { this.paused = true; this.dispatchEvent(new Event("pause")); }
  load() {}
  removeAttribute() { this.src = ""; }
}
beforeEach(() => {
  live.active = false;
  audio = new FakeAudio();
  vi.stubGlobal("Audio", class { constructor() { return audio; } });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const tracks: Track[] = ["Amber", "Blue", "Cloud"].map((display_name, i) => ({
  id: String(i), display_name, bpm: 100, camelot_key: "8A", duration_sec: 180, genre: "ambient",
}));

function Driver() {
  const player = usePlayer();
  return <>
    <button onClick={() => player.play(tracks[1], tracks, "saved-playlist")}>Other playlist</button>
    <button onClick={() => player.play(tracks[1], tracks, "catalog")}>Play middle card</button>
    <output data-testid="queue">{player.queue.map((t) => t.id).join(",")}</output>
  </>;
}
function Frame({ results = tracks, loading = false }: { results?: Track[]; loading?: boolean }) {
  return <PlayerProvider><CatalogPlayer tracks={results} loading={loading} label="Search results" /><Driver /></PlayerProvider>;
}

it("shows an idle player and plays all current results", async () => {
  render(<Frame />);
  expect(screen.getByLabelText("Catalog player")).toBeTruthy();
  expect(screen.getByTestId("catalog-queue-summary").textContent).toContain("3 tracks");
  fireEvent.click(screen.getByRole("button", { name: "Play results" }));
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Amber");
  expect(screen.getByTestId("queue").textContent).toBe("0,1,2");
  fireEvent.click(screen.getByLabelText("Next track"));
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Blue");
  fireEvent.click(screen.getByLabelText("Previous track"));
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Amber");
  fireEvent.click(screen.getByLabelText("Pause"));
  expect(audio.paused).toBe(true);
});

it("updates search results without restarting audio, then advances into them", async () => {
  const view = render(<Frame />);
  fireEvent.click(screen.getByRole("button", { name: "Play middle card" }));
  act(() => { audio.currentTime = 42; audio.dispatchEvent(new Event("timeupdate")); });
  const calls = audio.play.mock.calls.length;
  const src = audio.src;
  view.rerender(<Frame results={[tracks[2]]} />);
  expect(audio.src).toBe(src);
  expect(audio.currentTime).toBe(42);
  expect(audio.play).toHaveBeenCalledTimes(calls);
  expect(screen.getByTestId("queue").textContent).toBe("2");
  act(() => { audio.dispatchEvent(new Event("ended")); });
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Cloud");
  expect(screen.getByLabelText("Next track").hasAttribute("disabled")).toBe(true);
});

it("does not advance after empty results or while new results load", () => {
  const view = render(<Frame />);
  fireEvent.click(screen.getByRole("button", { name: "Play results" }));
  view.rerender(<Frame loading />);
  expect(screen.getByTestId("queue").textContent).toBe("");
  view.rerender(<Frame results={[]} />);
  expect(screen.getByRole("button", { name: "Play results" }).hasAttribute("disabled")).toBe(true);
  act(() => { audio.dispatchEvent(new Event("ended")); });
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Amber");
});

it("leaves queues from other pages alone until Play results is requested", () => {
  const view = render(<Frame />);
  fireEvent.click(screen.getByRole("button", { name: "Other playlist" }));
  view.rerender(<Frame results={[tracks[2]]} />);
  expect(screen.getByTestId("queue").textContent).toBe("0,1,2");
  expect(screen.getByTestId("catalog-player-title").textContent).toBe("Blue");
  fireEvent.click(screen.getByRole("button", { name: "Play results" }));
  expect(screen.getByTestId("queue").textContent).toBe("2");
});

it("seeks and adjusts volume through the existing audio element", async () => {
  render(<Frame />);
  fireEvent.click(screen.getByLabelText("Play"));
  act(() => { audio.dispatchEvent(new Event("loadedmetadata")); });
  fireEvent.change(screen.getByLabelText("Seek"), { target: { value: "50" } });
  expect(audio.currentTime).toBe(50);
  fireEvent.change(screen.getByLabelText("Volume"), { target: { value: "0.3" } });
  await waitFor(() => expect(audio.volume).toBe(0.3));
});

it("does not start catalog audio during a live session", () => {
  live.active = true;
  render(<Frame />);
  expect(screen.getByLabelText("Play").hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Play results" }).hasAttribute("disabled")).toBe(true);
  expect(audio.play).not.toHaveBeenCalled();
});
