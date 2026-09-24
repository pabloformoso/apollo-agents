"use client";
/**
 * LiveLeaveGuard — "a set is playing, leave anyway?" before a click or a
 * reload tears down the live engine.
 *
 * Render it on every page that owns a PRIMARY ``useLiveSession`` (never a
 * viewer: the OBS capture must not grow a modal). While ``active``:
 *
 *   - in-app links are caught in the CAPTURE phase on ``document`` — before
 *     React's root listener, so ``next/link`` never sees the click — and
 *     held behind a dialog;
 *   - reload / close / external navigation get the browser's native
 *     ``beforeunload`` prompt (the only thing a page may show there).
 *
 * Not covered: the browser's Back button and programmatic
 * ``router.push`` calls. Both are rare mid-set; the real fix is a player
 * that survives navigation.
 */
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Dialog } from "@/components/ember/Dialog";
import { Btn } from "@/components/ember/primitives";
import { leavingTo } from "@/lib/leave_guard";

interface LiveLeaveGuardProps {
  /** True while a set is connected and playing in this tab. */
  active: boolean;
  /** Shown in the dialog so the operator knows what they would stop. */
  trackName?: string | null;
}

export default function LiveLeaveGuard({ active, trackName }: LiveLeaveGuardProps) {
  const router = useRouter();
  const [pending, setPending] = useState<string | null>(null);
  // Set right before an approved navigation so neither listener blocks it.
  const releasedRef = useRef(false);

  useEffect(() => {
    if (!active) return;
    releasedRef.current = false;

    const onClick = (e: MouseEvent) => {
      if (releasedRef.current || e.defaultPrevented) return;
      const anchor = (e.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      const dest = leavingTo(
        {
          href: anchor.href,
          target: anchor.getAttribute("target"),
          download: anchor.hasAttribute("download"),
          button: e.button,
          metaKey: e.metaKey,
          ctrlKey: e.ctrlKey,
          shiftKey: e.shiftKey,
          altKey: e.altKey,
        },
        window.location.href,
      );
      if (!dest) return;
      e.preventDefault();
      e.stopPropagation();
      setPending(dest);
    };

    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (releasedRef.current) return;
      e.preventDefault();
      // Legacy browsers only show the prompt when returnValue is set.
      e.returnValue = "";
    };

    document.addEventListener("click", onClick, true);
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      document.removeEventListener("click", onClick, true);
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [active]);

  const stay = useCallback(() => setPending(null), []);
  const leave = useCallback(() => {
    if (!pending) return;
    releasedRef.current = true;
    const dest = pending;
    setPending(null);
    router.push(dest);
  }, [pending, router]);

  return (
    <Dialog open={active && pending !== null} onClose={stay} label="Leave the live set?">
      <div data-testid="live-leave-guard" className="p-7 flex flex-col gap-5">
        <div className="font-mono text-[11px] text-ember uppercase tracking-[0.22em]">
          ● live set playing
        </div>
        <div className="font-display italic text-3xl text-cream leading-tight">
          Leaving this page stops the set.
        </div>
        <p className="text-sm text-mute leading-relaxed">
          The music plays from this tab
          {trackName ? (
            <>
              {" "}— <span className="text-cream">{trackName}</span> stops
            </>
          ) : null}{" "}
          and the stream goes silent until someone reopens it. Open the other
          page in a new tab to keep the set going.
        </p>
        <div className="flex gap-3 justify-end">
          <Btn kind="ghost" onClick={leave} data-testid="live-leave-confirm">
            Leave &amp; stop the set
          </Btn>
          <Btn autoFocus onClick={stay} data-testid="live-leave-stay">
            Keep playing
          </Btn>
        </div>
      </div>
    </Dialog>
  );
}
