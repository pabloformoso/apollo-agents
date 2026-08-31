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
 */
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { NextResponse } from "next/server";

const PALETTE_PATH =
  process.env.ALGORAVE_PALETTE_PATH ??
  join(process.cwd(), "..", "..", "scripts", "algorave-spike", "palette.json");

export async function GET() {
  try {
    const raw = await readFile(PALETTE_PATH, "utf8");
    // Parsed and re-serialised on purpose: a malformed registry should fail
    // here, named, rather than reaching the page as an unparseable body.
    const palette = JSON.parse(raw);
    return NextResponse.json(palette, {
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
