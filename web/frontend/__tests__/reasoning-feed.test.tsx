import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ReasoningFeed } from "@/components/ember/ReasoningFeed";
import type { ReasoningEntry } from "@/lib/reasoning";

afterEach(cleanup);

const entries: ReasoningEntry[] = [
  { id: "1", ts: 1, kind: "thought", text: "The room wants it darker." },
  { id: "2", ts: 2, kind: "action", text: "Searching the catalog for what comes next", detail: "74–82 BPM · key 9A" },
  { id: "3", ts: 3, kind: "transition", text: "Bass swap into Quiet Ember", detail: "bass drops 0:12 in" },
];

describe("ReasoningFeed", () => {
  it("renders the panel with every entry, its label and its detail", () => {
    render(<ReasoningFeed entries={entries} />);
    const panel = screen.getByTestId("reasoning-panel");
    expect(panel.textContent).toContain("The room wants it darker.");
    expect(panel.textContent).toContain("74–82 BPM · key 9A");
    expect(panel.querySelectorAll("li")).toHaveLength(3);
    expect(panel.querySelector('[data-kind="transition"]')).not.toBeNull();
  });

  it("says so while thinking, in both shapes", () => {
    render(<ReasoningFeed entries={entries} thinking />);
    expect(screen.getByTestId("reasoning-thinking").textContent).toContain("thinking");
    cleanup();
    render(<ReasoningFeed entries={[]} thinking variant="overlay" />);
    expect(screen.getByTestId("reasoning-thinking").textContent).toContain("apollo is thinking");
  });

  it("renders nothing as an overlay when there is nothing to say — OBS must not show an empty box", () => {
    const { container } = render(<ReasoningFeed entries={[]} variant="overlay" />);
    expect(container.firstChild).toBeNull();
  });

  it("shows only the tail the limit allows", () => {
    render(<ReasoningFeed entries={entries} variant="overlay" limit={2} />);
    const overlay = screen.getByTestId("reasoning-overlay");
    expect(overlay.textContent).not.toContain("darker");
    expect(overlay.textContent).toContain("Quiet Ember");
  });

  it("explains an empty panel instead of showing a blank", () => {
    render(<ReasoningFeed entries={[]} />);
    expect(screen.getByTestId("reasoning-panel").textContent).toContain("Nothing decided yet");
  });
});
