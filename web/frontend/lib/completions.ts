/**
 * Autocomplete for the algorave editor — the rules, as pure functions.
 *
 * Deliberately separated from CodeMirror. What is worth getting right here is
 * not the popup, it is WHICH suggestions are legal at a given point, and that
 * is testable without a DOM:
 *
 *   - inside `s("…`      → the sounds the registry actually holds
 *   - inside `.bank("…`  → ONLY the banks that carry the sound just named
 *   - inside `note("…`   → note names
 *   - after a `.`        → the methods the dialect uses
 *
 * The second one is the point of the whole feature. The bank rule has been
 * enforced by the validator, documented in the palette browser, and explained
 * in the prompt — and a pair outside the matrix still plays SILENCE rather
 * than failing. Here it stops being a rule you can break: the wrong bank is
 * never offered.
 *
 * Suggestions are built from the live registry, never from a list in this file.
 * A sound added to `palette.json` is completable without a frontend change,
 * exactly as it is browsable without one.
 */
import { banksFor, type Palette } from "./palette";

export interface Suggestion {
  label: string;
  /** Shown greyed beside the label — why this is offered, or how it is played. */
  detail?: string;
  /** Ranked within a section; lower sorts first. */
  boost?: number;
}

export interface Completions {
  /** Absolute document offset where the token being completed starts. */
  from: number;
  options: Suggestion[];
}

/**
 * The dialect's methods. This IS a hand-written list, and it is the one place
 * that is defensible: these are Strudel's own function names, not our data.
 * Kept in step with the idiom paragraph in `strudel_mind.py` — the mind and the
 * human should be offered the same vocabulary.
 */
const METHODS: ReadonlyArray<[string, string]> = [
  ["n", "select the sample from a one-shot set"],
  ["bank", "drum machine — REQUIRED on drums, silence on instruments"],
  ["note", "pitch, for chromatic sounds"],
  ["gain", "level"],
  ["pan", "stereo position"],
  ["scale", "constrain to a key"],
  ["struct", "impose a rhythm"],
  ["add", "transpose"],
  ["speed", "playback rate"],
  ["late", "nudge later"],
  ["lpf", "low-pass cutoff"],
  ["lpq", "low-pass resonance"],
  ["hpf", "high-pass cutoff"],
  ["room", "reverb send"],
  ["roomsize", "reverb size"],
  ["delay", "delay send"],
  ["delaytime", "delay time"],
  ["delayfeedback", "delay feedback"],
  ["orbit", "effect bus"],
  ["attack", "envelope attack"],
  ["decay", "envelope decay"],
  ["sustain", "envelope sustain"],
  ["release", "envelope release"],
  ["detune", "detune"],
  ["unison", "unison voices"],
  ["spread", "unison spread"],
  ["vib", "vibrato"],
  ["swingBy", "swing"],
  ["every", "every n cycles"],
  ["sometimesBy", "probability"],
  ["degradeBy", "drop events"],
  ["off", "a copy, offset"],
  ["superimpose", "a copy, transformed"],
  ["jux", "a copy, panned"],
  ["mask", "gate by a pattern"],
  ["range", "map a signal"],
  ["slow", "stretch"],
  ["fast", "compress"],
  ["ply", "repeat each event"],
  ["chop", "cut each sample"],
  ["mul", "scale a control"],
  ["cpm", "cycles per minute"],
  ["midi", "send to a MIDI port instead of the speakers"],
];

const PITCH_CLASSES = ["c", "cs", "d", "ds", "e", "f", "fs", "g", "gs", "a", "as", "b"];
const OCTAVES = [1, 2, 3, 4, 5, 6];

/** Note names Strudel accepts, e.g. `c3`, `ds4`. */
export function noteNames(): string[] {
  const out: string[] = [];
  for (const oct of OCTAVES) for (const pc of PITCH_CLASSES) out.push(`${pc}${oct}`);
  return out;
}

/**
 * The sound named by the LAST `s("…")` before `offset`, or null.
 *
 * This is what makes bank completion correct: `.bank("` on its own cannot know
 * which banks are legal, but the sound it hangs off does.
 */
export function soundBefore(text: string): string | null {
  const matches = [...text.matchAll(/\bs\(\s*"([^"]*)"/g)];
  const last = matches[matches.length - 1];
  return last ? last[1] : null;
}

/** True when `offset` sits inside a double-quoted string in `text`. */
function insideString(text: string): boolean {
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    if (text[i] === "\\") {
      i++;
      continue;
    }
    if (text[i] === '"') quoted = !quoted;
  }
  return quoted;
}

/** The call whose string argument the cursor is inside — `s`, `bank`, `note`… */
function enclosingCall(before: string): { name: string; from: number } | null {
  const open = before.lastIndexOf('"');
  if (open === -1) return null;
  const head = before.slice(0, open);
  // `s(`, `.bank(`, `note(`, `n(` — optionally with whitespace.
  const m = head.match(/([A-Za-z_$][\w$]*)\s*\(\s*$/);
  return m ? { name: m[1], from: open + 1 } : null;
}

/**
 * What may be completed at the end of `before`.
 *
 * `before` is the whole document up to the cursor, so offsets returned are
 * absolute and the caller can splice directly.
 */
export function completionsFor(before: string, palette: Palette): Completions | null {
  if (insideString(before)) {
    const call = enclosingCall(before);
    if (!call) return null;
    const typed = before.slice(call.from);
    // Mini-notation holds several sounds in one string ("bd*4 ~ cp"); complete
    // the word under the cursor rather than the whole argument.
    const wordStart = Math.max(
      call.from,
      call.from + typed.length - (typed.match(/[\w#]*$/)?.[0].length ?? 0),
    );

    if (call.name === "s" || call.name === "sound") {
      return { from: wordStart, options: soundSuggestions(palette) };
    }
    if (call.name === "bank") {
      const sound = soundBefore(before);
      return { from: wordStart, options: bankSuggestions(palette, sound) };
    }
    if (call.name === "note" || call.name === "n") {
      return {
        from: wordStart,
        options: noteNames().map((n) => ({ label: n, detail: "note" })),
      };
    }
    return null;
  }

  // Outside a string: a method after a dot.
  const dot = before.match(/\.([A-Za-z_$][\w$]*)?$/);
  if (dot) {
    return {
      from: before.length - (dot[1]?.length ?? 0),
      options: METHODS.map(([label, detail]) => ({ label, detail })),
    };
  }
  return null;
}

function soundSuggestions(palette: Palette): Suggestion[] {
  const out: Suggestion[] = [];
  for (const d of palette.drums) {
    const banks = banksFor(palette, d);
    out.push({
      label: d,
      // Naming the banks here is the difference between "this needs a bank"
      // and knowing which one to reach for without leaving the keyboard.
      detail: banks.length ? `drum · .bank(${banks.slice(0, 3).join("/")}…)` : "drum · NO BANK CARRIES IT",
      boost: banks.length ? 2 : -1,
    });
  }
  for (const s of palette.synths) out.push({ label: s, detail: "synth · note()", boost: 1 });
  for (const i of palette.instruments) {
    out.push({
      label: i,
      detail: palette.pitched[i] === true ? "sampled · chromatic, note()" : "sampled · one-shots, .n()",
    });
  }
  return out;
}

function bankSuggestions(palette: Palette, sound: string | null): Suggestion[] {
  const all = Object.keys(palette.banks);
  if (!sound) return all.map((b) => ({ label: b, detail: "bank" }));

  // A sound that is not a drum takes no bank at all. Offering one here would
  // be offering silence, so the list is empty and says why.
  if (!palette.drums.includes(sound)) {
    return [
      {
        label: "",
        detail: `${sound} takes no bank — a .bank() on it plays silence`,
      },
    ].filter((o) => o.label.length > 0);
  }

  const carrying = banksFor(palette, sound);
  return all.map((b) => ({
    label: b,
    detail: carrying.includes(b) ? `carries ${sound}` : `does NOT carry ${sound} — silence`,
    boost: carrying.includes(b) ? 1 : -99,
  }));
}
