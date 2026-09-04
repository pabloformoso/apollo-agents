"use client";
/**
 * "Generate songs" — the entry to ACE from the CATALOG, not from a session.
 *
 * **Why it lives here and not only in the editor.** The editor's tile
 * (`GenerateTrackTile`) answers "fill THIS slot in the set I am building":
 * generation as a step inside a session. That is a real use and it stays. But
 * the other half — sit down, write a prompt, make songs, keep the ones that
 * work — has nothing to do with a session, and putting its only door inside
 * the session wizard made it unreachable from where a person actually thinks
 * about their library.
 *
 * Publishing already went straight to the catalog (`main.ingest_track`, the
 * same function `--ingest` runs), so nothing had to be decoupled: the dialog
 * takes `{open, onClose, defaultGenre}` and knows nothing about sessions. What
 * was missing was the door.
 *
 * Renders NOTHING when the generator is unavailable — the same rule the
 * editor's tile follows. The ACE box is off most of the time by design, and
 * absent is the normal look, not an error state.
 */
import { useState } from "react";
import { Btn } from "./primitives";
import { GeneratorDialog } from "./GeneratorDialog";
import { useGeneratorHealth } from "@/lib/generator";

export function GenerateSongs({
  defaultGenre = null,
  kind = "ghost",
}: {
  /** Preselects the form's genre — the filter you are looking at, usually. */
  defaultGenre?: string | null;
  kind?: "primary" | "ghost";
}) {
  const [open, setOpen] = useState(false);
  const health = useGeneratorHealth();

  // Loading and unavailable both render nothing, so the button appears once
  // and never flickers in and out.
  if (health.status !== "ready") return null;

  const blocked = health.health.blocked_by_live;

  return (
    <>
      <Btn
        kind={kind}
        data-testid="generate-songs"
        disabled={blocked}
        onClick={blocked ? undefined : () => setOpen(true)}
        title={
          blocked
            ? "A set is on air — generation shares the GPU with it"
            : undefined
        }
      >
        Generate songs
      </Btn>
      <GeneratorDialog
        open={open}
        onClose={() => setOpen(false)}
        defaultGenre={defaultGenre}
      />
    </>
  );
}
