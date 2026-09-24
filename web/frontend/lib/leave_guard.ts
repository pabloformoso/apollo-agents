/**
 * leave_guard — should this click take the operator away from a live set?
 *
 * The browser IS the live engine (``useLiveSession``): unmounting the page
 * closes the AudioContext and the WebSocket, and the backend stops the
 * engine. On 2026-09-23 a set was lost to a single click on "Catalog".
 * Until the player survives navigation, the page asks first.
 *
 * Pure so it can be tested without a DOM event loop; the component
 * (``components/LiveLeaveGuard.tsx``) feeds it the clicked anchor.
 */

export interface ClickInfo {
  /** The anchor's resolved ``href`` (``HTMLAnchorElement.href``). */
  href: string;
  /** The anchor's ``target`` attribute, if any. */
  target?: string | null;
  /** True if the anchor has a ``download`` attribute. */
  download?: boolean;
  button: number;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
}

/**
 * The in-app destination to confirm, or ``null`` when the click cannot
 * leave the page in THIS tab (new tab, download, other origin, hash link,
 * same page) and must be let through untouched.
 */
export function leavingTo(click: ClickInfo, current: string): string | null {
  if (click.button !== 0) return null;
  if (click.metaKey || click.ctrlKey || click.shiftKey || click.altKey) return null;
  if (click.download) return null;
  if (click.target && click.target !== "_self") return null;
  let dest: URL;
  let here: URL;
  try {
    here = new URL(current);
    dest = new URL(click.href, here);
  } catch {
    return null;
  }
  if (dest.origin !== here.origin) return null;
  if (dest.pathname === here.pathname && dest.search === here.search) return null;
  return dest.pathname + dest.search + dest.hash;
}
