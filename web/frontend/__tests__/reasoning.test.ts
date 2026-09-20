/**
 * The reasoning fold (lib/reasoning.ts) — pure, so it is pinned without a
 * socket. What matters is the SENTENCES: a tool call is a decision the room
 * can read only if the vocabulary turns its arguments into words.
 */
import { describe, expect, it } from "vitest";
import {
  EMPTY_REASONING,
  REASONING_MAX,
  describeDecision,
  describeToolCall,
  describeToolResult,
  describeTransition,
  reduceReasoning,
  type ReasoningState,
} from "@/lib/reasoning";

const T = 1_000;

function fold(events: Parameters<typeof reduceReasoning>[1][], from: ReasoningState = EMPTY_REASONING) {
  return events.reduce((s, e, i) => reduceReasoning(s, e, T + i), from);
}

describe("the vocabulary — a tool call becomes a sentence", () => {
  it("reads pick_next_track's criteria off its arguments", () => {
    const said = describeToolCall("pick_next_track", { bpm_min: 74, bpm_max: 82, key: "9A", mood: "warm" });
    expect(said?.text).toBe("Searching the catalog for what comes next");
    expect(said?.detail).toBe("74–82 BPM · key 9A · warm");
  });

  it("says when the DJ was allowed out of the genre", () => {
    expect(describeToolCall("extend_set", { track_id: "deep--x", allow_other_genre: true })?.detail).toBe(
      "deep--x · outside the genre, as asked",
    );
  });

  it("hides emit_chat — it is already in the chat feed", () => {
    expect(describeToolCall("emit_chat", { text: "hi" })).toBeNull();
  });

  it("falls back to the tool's name for anything unknown", () => {
    expect(describeToolCall("do_something_new", {})?.text).toBe("do something new");
  });

  it("counts the candidate table instead of quoting it", () => {
    const table = "| id | name |\n|---|---|\n| a | A |\n| b | B |\n| c | C |";
    expect(describeToolResult("pick_next_track", table)).toEqual({ kind: "outcome", text: "3 candidates in range" });
    expect(describeToolResult("pick_next_track", "| id |\n|---|")?.kind).toBe("warning");
  });

  it("keeps the engine's own words for a refused append, as a warning", () => {
    const said = describeToolResult("extend_set", "append_track: 'X' is already playing or queued — refusing duplicate append.");
    expect(said?.kind).toBe("warning");
    expect(said?.text).toContain("refusing duplicate append");
    expect(describeToolResult("extend_set", "Queued 'Quiet Ember' at position 5.")).toEqual({
      kind: "outcome",
      text: "Queued 'Quiet Ember' at position 5.",
    });
  });

  it("says nothing for a state read's result", () => {
    expect(describeToolResult("get_live_state", "…")).toBeNull();
  });
});

describe("the vocabulary — the engine's verdicts", () => {
  it("names a bass swap with the drop time and the phrase lock", () => {
    const said = describeTransition(
      { transition_style: "bass_swap", phrase_tier: "16-bar", bass_swap: { drop_at_incoming_sec: 12.4 } },
      "Quiet Ember",
    );
    expect(said.text).toBe("Bass swap into Quiet Ember");
    expect(said.detail).toBe("bass drops 0:12 in · locked to a 16-bar phrase");
  });

  it("calls a fallback tier what it is", () => {
    expect(describeTransition({ transition_style: "smooth_blend", phrase_tier: "fallback" }, "X")).toEqual({
      text: "Smooth blend into X",
      detail: "no phrase lock",
    });
    expect(describeTransition({ phrase_tier: "fallback" }, null)).toEqual({
      text: "Fade into the next track",
      detail: "no phrase anchor found",
    });
  });

  it("explains the safety net's tier in words", () => {
    expect(describeDecision({ kind: "endless_pick", tier: "widened", track: { display_name: "Soft Focus" } })).toEqual({
      text: "Safety net queued Soft Focus",
      detail: "from a neighbouring genre · the DJ did not answer in time",
    });
    expect(describeDecision({ kind: "something_else" })).toBeNull();
  });
});

describe("the fold", () => {
  it("streams a thought open, then closes it on the final message without duplicating it", () => {
    const s = fold([
      { type: "text_delta", content: "The room " },
      { type: "text_delta", content: "asked for darker." },
      { type: "live_message", role: "assistant", content: "The room asked for darker." },
    ]);
    expect(s.entries).toHaveLength(1);
    expect(s.entries[0]).toMatchObject({ kind: "thought", text: "The room asked for darker.", open: false });
    expect(s.thinking).toBe(false);
  });

  it("is thinking from the first token until the final message", () => {
    const mid = fold([{ type: "text_delta", content: "Hm" }]);
    expect(mid.thinking).toBe(true);
    expect(mid.entries[0].open).toBe(true);
    expect(fold([{ type: "live_message", role: "assistant", content: "done" }], mid).thinking).toBe(false);
  });

  it("closes the thought when a tool is called, and drops an empty one", () => {
    const s = fold([
      { type: "text_delta", content: " " },
      { type: "tool_call", name: "skip_track", input: {} },
    ]);
    expect(s.entries.map((e) => e.kind)).toEqual(["action"]);
    expect(s.entries[0].text).toBe("Skipping to the next track");
  });

  it("treats a final message with no stream as the whole thought (the OBS replay case)", () => {
    const s = fold([{ type: "live_message", role: "assistant", content: "Holding the energy here." }]);
    expect(s.entries).toEqual([expect.objectContaining({ kind: "thought", text: "Holding the energy here." })]);
  });

  it("ignores the user's own messages", () => {
    expect(fold([{ type: "live_message", role: "user", content: "darker" }]).entries).toHaveLength(0);
  });

  it("announces a transition once per next track, however often the engine repeats it", () => {
    const evt = {
      type: "approaching_crossfade" as const,
      next_track: { id: "t2", display_name: "Quiet Ember" },
      phase_lock: { transition_style: "bass_swap", phrase_tier: "16-bar", bass_swap: { drop_at_incoming_sec: 8 } },
    };
    const s = fold([evt, evt, { ...evt, next_track: { id: "t3", display_name: "Third" } }]);
    expect(s.entries.map((e) => e.text)).toEqual(["Bass swap into Quiet Ember", "Bass swap into Third"]);
  });

  it("folds the engine's warning and decision, and leaves unknown events alone", () => {
    const s = fold([
      { type: "critic_warning", message: "No beatgrid on either side — linear fade." },
      { type: "decision", kind: "endless_pick", tier: "in_genre", track: { id: "x", display_name: "X" } },
      { type: "playback_pos" },
    ]);
    expect(s.entries.map((e) => e.kind)).toEqual(["warning", "decision"]);
  });

  it("caps the feed at the tail", () => {
    const many = Array.from({ length: REASONING_MAX + 20 }, (_, i) => ({
      type: "tool_call" as const,
      name: "skip_track",
      input: { i },
    }));
    const s = fold(many);
    expect(s.entries).toHaveLength(REASONING_MAX);
  });
});
