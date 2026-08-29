"use client";
/**
 * Apollo G1 — "Generate (ACE)" entry tile.
 *
 * Sits beside the Editor's "Add a track" tile: same dashed-outline shape, so
 * generating a track reads as a sibling of picking one from the catalog
 * rather than a bolted-on panel.
 *
 * Feature-flagged by `GET /api/generator/health`:
 *   - `available: false` → renders NOTHING. The ACE box is off most of the
 *     time by design, and an unavailable generator is a normal state, not an
 *     error worth a slot on screen.
 *   - `blocked_by_live: true` → visible but disabled, with the VRAM-protocol
 *     tooltip. ACE holds ~12.5 GB of the shared 16 GB once loaded, which
 *     starves the live DJ's model, so generation waits until the set is off
 *     air. The POST's 409 is the authoritative guard; this is the courtesy.
 */
import * as React from "react";
import { useGeneratorHealth } from "@/lib/generator";
import { Crumb } from "./primitives";

/** Shown on the disabled tile — the user-facing half of the VRAM protocol. */
export const VRAM_BLOCKED_TOOLTIP =
  "VRAM protocol: a set is on air. Generating now would starve the live DJ's model.";

function Spark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      strokeWidth="1.5"
      className={"stroke-current fill-none " + (className ?? "")}
      aria-hidden
    >
      <path d="M8 1.5l1.6 4.9 4.9 1.6-4.9 1.6L8 14.5l-1.6-4.9L1.5 8l4.9-1.6z" />
    </svg>
  );
}

export function GenerateTrackTile({ onClick }: { onClick: () => void }) {
  const health = useGeneratorHealth();

  // Loading and unavailable both render nothing — the tile appears once the
  // generator has answered, and never flickers in and out.
  if (health.status !== "ready") return null;

  const blocked = health.health.blocked_by_live;

  return (
    <button
      type="button"
      onClick={blocked ? undefined : onClick}
      disabled={blocked}
      data-testid="generator-open"
      title={blocked ? VRAM_BLOCKED_TOOLTIP : undefined}
      aria-label="Generate a track with ACE-Step"
      className={
        "flex-[0_0_200px] p-4 flex flex-col items-center justify-center gap-2 " +
        "border border-dashed bg-transparent font-sans " +
        (blocked
          ? "border-line2 text-faint opacity-50 cursor-not-allowed"
          : "border-ember/50 text-ember-text cursor-pointer hover:border-ember")
      }
    >
      <Spark className={blocked ? "text-faint" : "text-ember"} />
      <span className="text-xs">Generate (ACE)</span>
      <Crumb tone={blocked ? "faint" : "ember"}>
        {blocked ? "on air" : "new material"}
      </Crumb>
    </button>
  );
}
