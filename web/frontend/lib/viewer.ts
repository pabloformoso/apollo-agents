"use client";
/**
 * §11 S8 — the viewer gate, shared by every performance surface (§11.3 seam 3).
 *
 * `?viewer=1` is the URL an OBS Browser Source is pointed at. The flag is
 * THREE-STATE on purpose, and the reason is scar tissue from v3.6.2:
 *
 *   `null` means "not resolved yet" — the first render, before the mount
 *   effect has read the URL. Anything that attaches to a session MUST wait for
 *   that. A `?viewer=1` page whose first connect races the flag lands on the
 *   PRIMARY endpoint, displaces the operator's tab, and its own teardown then
 *   stops the engine: an OBS Browser Source that silently kills the session it
 *   is mirroring.
 *
 * Treating "not yet known" as "not a viewer" is the bug. Callers must branch on
 * all three states, which is why this returns the raw flag and a convenience
 * boolean rather than just the boolean.
 */
import { useEffect, useState } from "react";

export interface ViewerFlag {
  /** null until the URL has been read on mount. Never treat null as false. */
  flag: boolean | null;
  /** True only once resolved AND `?viewer=1`. */
  isViewer: boolean;
  /** False until the URL has been read — gate connections on this. */
  resolved: boolean;
}

export const VIEWER_PARAM = "viewer";

export function useViewerFlag(): ViewerFlag {
  const [flag, setFlag] = useState<boolean | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    setFlag(params.get(VIEWER_PARAM) === "1");
  }, []);

  return { flag, isViewer: flag === true, resolved: flag !== null };
}

/** The URL to paste into an OBS Browser Source for a given page. */
export function viewerUrlFor(href: string): string {
  const url = new URL(href);
  url.searchParams.set(VIEWER_PARAM, "1");
  return url.toString();
}
