/**
 * §11 S7 — the palette, read from the one file that defines it.
 *
 * `scripts/algorave-spike/palette.json` is the registry §10 built: the
 * validator gates against it, `strudel_mind` prompts from it, and the
 * playground plays from it. This route reads THAT file — no copy, no
 * re-declaration — so what the page can offer and what the mind may write stay
 * one vocabulary, which is the whole point of the registry existing.
 *
 * Read at request time rather than imported, so adding a sound to the JSON
 * shows up without rebuilding the app.
 *
 * It also answers a question the registry does NOT record: is a sound played
 * with `note(...)` or selected with `.n(i)`? The sample maps already know —
 * a map whose entry is an OBJECT is keyed by note name and therefore
 * chromatic (`piano`, `balafon`), while a flat ARRAY is addressed by index
 * (`gretsch`, `tabla`, and — discovered 2026-09-01 — `conga`, which had been
 * written as pitched since the day it was added). Deriving it from the maps
 * beats curating it by hand: the data cannot go stale against itself.
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { NextResponse } from "next/server";

const PALETTE_PATH =
  process.env.ALGORAVE_PALETTE_PATH ??
  join(process.cwd(), "..", "..", "scripts", "algorave-spike", "palette.json");

/**
 * Sample maps, fetched once per process. They are pinned by URL and a few tens
 * of KB each; refetching them per request would put a CDN round trip in front
 * of a page load for data that does not change.
 */
const mapCache = new Map<string, Record<string, unknown>>();

async function sampleMap(url: string): Promise<Record<string, unknown> | null> {
  const hit = mapCache.get(url);
  if (hit) return hit;
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return null;
    const json = (await res.json()) as Record<string, unknown>;
    mapCache.set(url, json);
    return json;
  } catch {
    // A dead CDN must not take the palette with it: callers treat a missing
    // answer as "unknown", which falls back to the previous behaviour.
    return null;
  }
}

/**
 * sound → true when the map addresses it by NOTE NAME. Absent means the map
 * could not be read, and the caller must not guess.
 */
async function pitchedIndex(
  sources: { json: string }[],
): Promise<Record<string, boolean>> {
  const out: Record<string, boolean> = {};
  const maps = await Promise.all(sources.map((s) => sampleMap(s.json)));
  for (const map of maps) {
    if (!map) continue;
    for (const [name, value] of Object.entries(map)) {
      if (name.startsWith("_")) continue;
      // Object → keyed by note (A0, C1, Ds1…) → chromatic.
      // Array  → a flat list of files → selected with .n(i).
      out[name] = !Array.isArray(value) && typeof value === "object" && value !== null;
    }
  }
  return out;
}

export async function GET() {
  try {
    const raw = await readFile(PALETTE_PATH, "utf8");
    // Parsed and re-serialised on purpose: a malformed registry should fail
    // here, named, rather than reaching the page as an unparseable body.
    const palette = JSON.parse(raw);
    const pitched = await pitchedIndex(palette.sources ?? []);
    return NextResponse.json({ ...palette, pitched }, {
      headers: { "cache-control": "no-store" },
    });
  } catch (err) {
    return NextResponse.json(
      {
        error: "the palette registry could not be read",
        detail: `${PALETTE_PATH}: ${String(err)}`,
      },
      { status: 502 },
    );
  }
}
