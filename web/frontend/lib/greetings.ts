/**
 * Greeting-toast queue logic (v3.7.0).
 *
 * Pure functions only — the GreetingOverlay component drives timing;
 * everything decision-shaped lives here so vitest can cover the matrix.
 *
 * Design (agreed 2026-07-12):
 *  - One toast visible at a time, calm cadence — this renders on a
 *    lofi stream, not a hype raid overlay.
 *  - The YouTube poller delivers messages in up-to-60s batches, so
 *    greetings arrive in clumps: when 3+ are waiting, collapse them
 *    into one collective toast instead of a toast machine gun.
 */

export interface Greeting {
  /** Monotonic per-session id assigned by the hook — burst events share
   *  the same ``ts`` (one poll batch), so identity needs its own field. */
  id: number;
  author: string;
  kind: "first" | "returning";
  /** Client receive time (ms). */
  ts: number;
}

export interface ToastPlan {
  /** Text without the leading emoji — the component owns presentation. */
  text: string;
  /** Authors consumed from the queue by this toast. */
  consumed: number;
}

/** How many waiting greetings trigger a collective toast. */
export const COALESCE_THRESHOLD = 3;
/** Max names listed in a collective toast before "y N más". */
export const COALESCE_MAX_NAMES = 3;
/** How long a single toast stays on screen (ms). */
export const TOAST_DURATION_MS = 6_000;
/** Quiet gap between consecutive toasts (ms). */
export const TOAST_GAP_MS = 4_000;

/**
 * Given the current waiting queue, produce the next toast (or null when
 * the queue is empty). The caller removes `consumed` entries and waits
 * TOAST_DURATION_MS + TOAST_GAP_MS before asking again.
 */
export function nextToast(queue: Greeting[]): ToastPlan | null {
  if (queue.length === 0) return null;
  if (queue.length < COALESCE_THRESHOLD) {
    const g = queue[0];
    return { text: greetingLine(g), consumed: 1 };
  }
  // Burst → one collective toast consumes the ENTIRE waiting queue.
  const names = queue.slice(0, COALESCE_MAX_NAMES).map((g) => `@${g.author}`);
  const rest = queue.length - names.length;
  const listed =
    names.length > 1
      ? `${names.slice(0, -1).join(", ")} y ${names[names.length - 1]}`
      : names[0];
  const tail = rest > 0 ? ` y ${rest} más` : "";
  return { text: `Bienvenidos ${listed}${tail}`, consumed: queue.length };
}

/**
 * Template pool for individual greetings — deterministic pick by author
 * so the same person always gets the same line (and tests stay stable),
 * while different chatters see variety.
 */
const FIRST_TEMPLATES = [
  (n: string) => `Bienvenid@ @${n}`,
  (n: string) => `@${n} en la sala 🎧`,
  (n: string) => `Hola @${n}, ponte cómod@`,
  (n: string) => `@${n} se une al viaje`,
  (n: string) => `Buenas @${n} ✨`,
];

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = (h * 31 + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function greetingLine(g: Greeting): string {
  if (g.kind === "returning") {
    return `¡@${g.author} de vuelta por aquí!`;
  }
  return FIRST_TEMPLATES[hashName(g.author) % FIRST_TEMPLATES.length](g.author);
}
