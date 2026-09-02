/**
 * The jam survives a reload — F5, a crash, someone else driving the tab.
 *
 * **What is NOT saved is the important half**, and the rule comes from the
 * playground (§9.1, §9.2): the PEN and the B2B mode never persist. A freshly
 * loaded page must never fire an LLM call by itself and must never wake up
 * alternating, so it is always HUMAN and always FREE on arrival. Restoring
 * `pen: "mind"` would mean a reload starts asking the mind for mutations with
 * nobody watching — the one behaviour a performance tool must not have.
 *
 * The transport is not saved either: a reloaded page is stopped. Nothing should
 * start making sound because a browser refreshed.
 *
 * Storage can be absent or throwing (a private window, storage disabled), and
 * the page has to work without it. Every call is guarded; failure means the jam
 * simply does not persist, which is a degradation and not an error.
 */

const KEY = "apollo-algorave-v1";

/** Only the things a performer would be annoyed to retype. */
export interface SavedSession {
  buffer: string;
  intent: string;
  phraseBars: number;
  b2bBars: number;
  bpm: number;
  genre: string;
  key: string;
  /**
   * Which model to ask. A PREFERENCE, like genre and key — not an armed
   * scheduler, so unlike the pen and B2B it is safe to restore: a reloaded
   * page still asks nothing until a human presses something.
   *
   * Empty means "the mind's default". A saved name the mind no longer offers
   * must fall back to that rather than being sent and refused, and the page
   * checks it against the published list for exactly that reason.
   */
  model: string;
}

export function saveSession(s: SavedSession): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ v: 1, ...s }));
  } catch {
    // Storage unavailable — the jam just does not persist.
  }
}

/**
 * Reads a saved session, or null. Every field is checked: a shape written by
 * an older build must degrade to "nothing saved" rather than putting a string
 * where a number belongs and breaking the scheduler mid-set.
 */
export function loadSession(): SavedSession | null {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(KEY);
  } catch {
    return null;
  }
  if (!raw) return null;

  try {
    const o = JSON.parse(raw) as Record<string, unknown>;
    if (o.v !== 1) return null;

    const str = (v: unknown, fallback: string) =>
      typeof v === "string" ? v : fallback;
    const num = (v: unknown, fallback: number) =>
      typeof v === "number" && Number.isFinite(v) && v > 0 ? v : fallback;

    // A buffer is the one field with no sensible fallback: without it there is
    // nothing worth restoring, so an absent one voids the whole snapshot.
    if (typeof o.buffer !== "string" || o.buffer.length === 0) return null;

    return {
      buffer: o.buffer,
      intent: str(o.intent, ""),
      phraseBars: num(o.phraseBars, 8),
      b2bBars: num(o.b2bBars, 16),
      bpm: num(o.bpm, 124),
      genre: str(o.genre, "deep"),
      key: str(o.key, "A:minor"),
      model: str(o.model, ""),
    };
  } catch {
    return null;
  }
}

export function clearSession(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    // Nothing to do: there was nothing to clear.
  }
}
