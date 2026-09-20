/**
 * The live DJ's reasoning, as a feed the audience can read.
 *
 * Everything here was already on the wire. ``run_agent_streaming`` publishes
 * ``text_delta`` / ``tool_call`` / ``tool_result`` through the same emitter
 * the live WebSocket uses — and that emitter fans out to every OBS viewer —
 * but ``useLiveSession`` used to drop the three of them one line before
 * they could be drawn. The engine's own verdicts (the transition style it
 * chose, the safety-net pick, a phrase lock it could not land) were in the
 * same position: computed, sent or logged, never shown.
 *
 * This module is pure so the folding is testable without a socket: a
 * reducer over the events, and the small vocabulary that turns a tool call
 * such as ``pick_next_track(bpm_min=74, bpm_max=82, key="9A")`` into a
 * sentence a room can read. The hook only calls ``reduceReasoning``; the
 * panel only renders ``ReasoningEntry``.
 */

export type ReasoningKind =
  /** The model's own words, streamed. ``open`` while it is still talking. */
  | "thought"
  /** A tool the model called — what it decided to DO. */
  | "action"
  /** What that tool answered — the world's reply to the decision. */
  | "outcome"
  /** A transition the engine planned: style, phrase lock, when the drop lands. */
  | "transition"
  /** A deterministic pick the ENGINE made (the safety net), not the model. */
  | "decision"
  /** Something the engine could not do the good way and says so. */
  | "warning";

export interface ReasoningEntry {
  id: string;
  ts: number;
  kind: ReasoningKind;
  text: string;
  /** Secondary line: the numbers behind the sentence. */
  detail?: string;
  /** A thought still streaming in. */
  open?: boolean;
  /** Dedupe key for events the engine re-emits (a transition is announced once). */
  key?: string;
}

export interface ReasoningState {
  entries: ReasoningEntry[];
  /** True between the first token of a turn and its final message. */
  thinking: boolean;
}

export const EMPTY_REASONING: ReasoningState = { entries: [], thinking: false };

/** Long broadcasts must not accumulate a night of thoughts in memory. */
export const REASONING_MAX = 200;

/** The subset of wire events the reducer understands. Anything else is a no-op. */
export type ReasoningEvent =
  | { type: "text_delta"; content?: string }
  | { type: "tool_call"; name?: string; input?: Record<string, unknown> }
  | { type: "tool_result"; name?: string; result?: string }
  | { type: "live_message"; role?: string; content?: string }
  | {
      type: "approaching_crossfade";
      next_track?: { id?: string; display_name?: string } | null;
      phase_lock?: PhaseLockLike | null;
    }
  | { type: "critic_warning"; message?: string; reason?: string }
  | {
      type: "decision";
      kind?: string;
      tier?: string;
      track?: { id?: string; display_name?: string } | null;
      picked_by?: string;
    }
  | { type: string };

/** What ``describeTransition`` reads off ``phase_lock``; the full payload has more. */
export interface PhaseLockLike {
  transition_style?: string;
  phrase_tier?: string;
  xfade_sec?: number;
  bass_swap?: { drop_at_incoming_sec?: number } | null;
}

// ---------------------------------------------------------------------------
// The vocabulary
// ---------------------------------------------------------------------------

const TOOL_SENTENCES: Record<string, string> = {
  skip_track: "Skipping to the next track",
  crossfade_now: "Starting the crossfade now",
  extend_track: "Staying on this track a little longer",
  queue_swap: "Reordering the queue",
  get_live_state: "Checking where the set is",
  get_perception_window: "Listening to the room",
};

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

/**
 * One sentence per tool call, with the criteria as the detail line. Returns
 * null for calls that are already visible another way (``emit_chat`` lands in
 * the chat feed) so the same words do not appear twice on stream.
 */
export function describeToolCall(
  name: string,
  input: Record<string, unknown> = {},
): { text: string; detail?: string } | null {
  switch (name) {
    case "emit_chat":
      return null;
    case "pick_next_track": {
      const lo = num(input.bpm_min);
      const hi = num(input.bpm_max);
      const parts: string[] = [];
      if (lo !== null && hi !== null) parts.push(`${Math.round(lo)}–${Math.round(hi)} BPM`);
      const key = str(input.key);
      if (key) parts.push(`key ${key}`);
      const mood = str(input.mood);
      if (mood) parts.push(mood);
      if (input.include_other_genres === true) parts.push("any genre");
      return { text: "Searching the catalog for what comes next", detail: parts.join(" · ") || undefined };
    }
    case "extend_set": {
      const id = str(input.track_id);
      const detail = [id, input.allow_other_genre === true ? "outside the genre, as asked" : null]
        .filter(Boolean)
        .join(" · ");
      return { text: "Queuing the continuation", detail: detail || undefined };
    }
    case "set_crossfade_point": {
      const at = num(input.position_sec ?? input.seconds ?? input.at_sec);
      return {
        text: "Moving the crossfade point",
        detail: at !== null ? `to ${formatClock(at)} into the track` : undefined,
      };
    }
    default: {
      const known = TOOL_SENTENCES[name];
      if (known) return { text: known };
      return { text: name.replace(/_/g, " ") };
    }
  }
}

/**
 * What a tool answered, when the answer is worth a line. The candidate table
 * becomes a count; a refused append becomes a warning with the engine's own
 * words, because that sentence names the rule that fired.
 */
export function describeToolResult(
  name: string,
  result = "",
): { kind: "outcome" | "warning"; text: string } | null {
  const first = result.split("\n").find((l) => l.trim()) ?? "";
  switch (name) {
    case "pick_next_track": {
      const rows = result.split("\n").filter((l) => l.trim().startsWith("|")).length;
      const candidates = Math.max(0, rows - 2); // header + separator
      if (rows === 0) return { kind: "outcome", text: clip(first, 140) || "No candidates in range" };
      return {
        kind: candidates === 0 ? "warning" : "outcome",
        text: candidates === 0 ? "Nothing in range — widening the search" : `${candidates} candidate${candidates === 1 ? "" : "s"} in range`,
      };
    }
    case "extend_set": {
      const refused = /^append_track:|refus|not eligible|cannot|can't/i.test(first);
      return { kind: refused ? "warning" : "outcome", text: clip(first, 160) };
    }
    default:
      return null;
  }
}

/**
 * The transition the engine planned, read off ``phase_lock``. The verdict was
 * always there — the audio scheduler consumed it — but it had never been said.
 */
export function describeTransition(
  lock: PhaseLockLike | null | undefined,
  nextName: string | null | undefined,
): { text: string; detail?: string } {
  const into = nextName ? `into ${nextName}` : "into the next track";
  const tier = lock?.phrase_tier;
  const locked = tier && tier !== "fallback" ? `locked to a ${tier} phrase` : "no phrase lock";
  switch (lock?.transition_style) {
    case "bass_swap": {
      const drop = num(lock?.bass_swap?.drop_at_incoming_sec);
      return {
        text: `Bass swap ${into}`,
        detail: [drop !== null ? `bass drops ${formatClock(drop)} in` : null, locked].filter(Boolean).join(" · "),
      };
    }
    case "drift": {
      const secs = num(lock?.xfade_sec);
      return { text: `Long drift ${into}`, detail: secs !== null ? `${Math.round(secs)} s fade · beatless` : undefined };
    }
    case "smooth_blend":
      return { text: `Smooth blend ${into}`, detail: locked };
    default:
      return { text: `Fade ${into}`, detail: tier === "fallback" ? "no phrase anchor found" : undefined };
  }
}

const TIER_TEXT: Record<string, string> = {
  in_genre: "unheard, in genre",
  widened: "from a neighbouring genre",
  recycled: "recycled — the whole catalog has played",
};

export function describeDecision(evt: {
  kind?: string;
  tier?: string;
  track?: { id?: string; display_name?: string } | null;
}): { text: string; detail?: string } | null {
  if (evt.kind !== "endless_pick") return null;
  const name = evt.track?.display_name || evt.track?.id || "a track";
  return {
    text: `Safety net queued ${name}`,
    detail: [evt.tier ? TIER_TEXT[evt.tier] ?? evt.tier : null, "the DJ did not answer in time"].filter(Boolean).join(" · "),
  };
}

// ---------------------------------------------------------------------------
// The fold
// ---------------------------------------------------------------------------

let seq = 0;
function entry(kind: ReasoningKind, text: string, now: number, extra: Partial<ReasoningEntry> = {}): ReasoningEntry {
  seq += 1;
  return { id: `r-${now}-${seq}`, ts: now, kind, text, ...extra };
}

function cap(entries: ReasoningEntry[]): ReasoningEntry[] {
  return entries.length > REASONING_MAX ? entries.slice(-REASONING_MAX) : entries;
}

function closeOpenThought(entries: ReasoningEntry[]): ReasoningEntry[] {
  const last = entries[entries.length - 1];
  if (!last || last.kind !== "thought" || !last.open) return entries;
  const closed = { ...last, open: false, text: last.text.trim() };
  // A turn that only called tools leaves an empty thought behind: drop it.
  return closed.text ? [...entries.slice(0, -1), closed] : entries.slice(0, -1);
}

/**
 * Fold one wire event into the feed. Pure: same input, same output, and the
 * hook can call it from a state setter.
 */
export function reduceReasoning(
  state: ReasoningState,
  evt: ReasoningEvent,
  now: number = Date.now(),
): ReasoningState {
  const { entries } = state;
  switch (evt.type) {
    case "text_delta": {
      const content = (evt as { content?: string }).content ?? "";
      const last = entries[entries.length - 1];
      if (last && last.kind === "thought" && last.open) {
        const next = [...entries.slice(0, -1), { ...last, text: last.text + content }];
        return { entries: next, thinking: true };
      }
      if (!content.trim()) return { ...state, thinking: true };
      return { entries: cap([...entries, entry("thought", content.trimStart(), now, { open: true })]), thinking: true };
    }
    case "tool_call": {
      const e = evt as { name?: string; input?: Record<string, unknown> };
      const closed = closeOpenThought(entries);
      const said = describeToolCall(e.name ?? "", e.input ?? {});
      if (!said) return { entries: closed, thinking: true };
      return { entries: cap([...closed, entry("action", said.text, now, { detail: said.detail })]), thinking: true };
    }
    case "tool_result": {
      const e = evt as { name?: string; result?: string };
      const said = describeToolResult(e.name ?? "", e.result ?? "");
      if (!said) return { ...state, thinking: true };
      return { entries: cap([...entries, entry(said.kind, said.text, now)]), thinking: true };
    }
    case "live_message": {
      const e = evt as { role?: string; content?: string };
      if (e.role && e.role !== "assistant") return state;
      const last = entries[entries.length - 1];
      if (last && last.kind === "thought" && last.open) {
        return { entries: closeOpenThought(entries), thinking: false };
      }
      // No stream preceded it: a replay for a late viewer, or an older
      // backend. The final text is then the whole thought.
      const content = (e.content ?? "").trim();
      if (!content) return { ...state, thinking: false };
      return { entries: cap([...entries, entry("thought", content, now)]), thinking: false };
    }
    case "approaching_crossfade": {
      const e = evt as Extract<ReasoningEvent, { type: "approaching_crossfade" }>;
      const key = `transition:${e.next_track?.id ?? "?"}`;
      if (entries.some((x) => x.key === key)) return state;
      const said = describeTransition(e.phase_lock, e.next_track?.display_name);
      return { ...state, entries: cap([...entries, entry("transition", said.text, now, { detail: said.detail, key })]) };
    }
    case "critic_warning": {
      const e = evt as { message?: string; reason?: string };
      const text = e.message || e.reason || "The next transition could not lock to a phrase";
      return { ...state, entries: cap([...entries, entry("warning", text, now)]) };
    }
    case "decision": {
      const said = describeDecision(evt as Extract<ReasoningEvent, { type: "decision" }>);
      if (!said) return state;
      return { ...state, entries: cap([...entries, entry("decision", said.text, now, { detail: said.detail })]) };
    }
    case "error":
      return { ...state, thinking: false };
    default:
      return state;
  }
}

// ---------------------------------------------------------------------------

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function clip(text: string, max: number): string {
  const t = text.trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}
