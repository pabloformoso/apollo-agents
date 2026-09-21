"use client";
/**
 * Apollo v2.6.0 — top-level Shell.
 *
 * Port of the <Shell> from
 * docs/design/apollo-claude-design/apollo/project/prototype-shell.jsx.
 *
 * The prototype owns its own Router context; in production we use the
 * Next.js App Router (next/link + usePathname), so this component is a
 * thin presentational wrapper:
 *
 *   - Sticky header with ApolloMark left, segmented nav center,
 *     username right.
 *   - The Live route hides the nav entirely (the prototype's
 *     ``hideNav`` flag) — broadcasting needs the screen.
 */
import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ApolloMark, Crumb } from "./primitives";

/**
 * Every product surface, for the active-tab mapping and the per-route
 * behaviour below — but only the ROOMS are tabs (`nav: true`). Create is
 * a journey you start from Home ("Start a session", the showcase); Perform
 * is where a session sends you ("Apollo, take the booth"). As top-level
 * tabs they read as two more places to be, which in a room full of people
 * is two more places to lose them (2026-09-21).
 */
export const ROUTES = [
  { id: "library", label: "Home", href: "/dashboard", nav: true },
  { id: "catalog", label: "Catalog", href: "/catalog", nav: true },
  { id: "generations", label: "Generations", href: "/generations", nav: true },
  { id: "create", label: "Create", href: "/brief", nav: false },
  { id: "perform", label: "Perform", href: "/live", nav: false },
  { id: "algorave", label: "Algorave", href: "/algorave", nav: true },
  { id: "settings", label: "Settings", href: "/settings", nav: true },
] as const;

/** The tabs, in order: Home · Catalog · Generations · Algorave · Settings. */
export const NAV_ROUTES = ROUTES.filter((r) => r.nav);

type RouteId = (typeof ROUTES)[number]["id"];

/** Map a Next pathname to a product surface, not an implementation step. */
function routeIdForPath(pathname: string | null): RouteId {
  if (!pathname || pathname === "/" || pathname.startsWith("/dashboard")) return "library";
  if (pathname.startsWith("/generations")) return "generations";
  if (pathname.startsWith("/catalog")) return "catalog";
  // Brief, curate, editor and render are stages of one Create journey.
  if (["/brief", "/curate", "/editor", "/render"].some((path) => pathname.startsWith(path))) return "create";
  if (pathname.startsWith("/algorave")) return "algorave";
  if (pathname.startsWith("/live")) return "perform";
  if (pathname.startsWith("/settings")) return "settings";
  return "library";
}

export type ShellProps = {
  children: React.ReactNode;
  /** Optional secondary line shown next to the wordmark
   * (e.g. "lofi · garden chill"). Hidden on dashboard. */
  sessionLabel?: string | null;
  /** User pill text (top-right). Falls back to "guest" when absent. */
  username?: string | null;
  /** When true, clamp the layout to exactly one viewport (no page scroll).
   * Used by the dashboard/login splash screens. */
  fitViewport?: boolean;
  /** Force the nav away for a full-bleed surface. `/live` hides it by route
   * because it is always broadcasting; `/algorave` hides it only in its
   * immersive mode, which the route alone cannot know (§11 S4). */
  hideNav?: boolean;
};

export function Shell({
  children,
  sessionLabel,
  username,
  fitViewport,
  hideNav: hideNavProp,
}: ShellProps) {
  const pathname = usePathname();
  const route = routeIdForPath(pathname);
  const hideNav = hideNavProp ?? route === "perform";

  return (
    <div
      className={
        "flex w-full flex-col bg-ink text-ember-text font-sans " +
        (fitViewport ? "h-screen overflow-hidden" : "min-h-screen")
      }
    >
      {!hideNav && (
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-ink px-9 py-[18px]">
          <Link
            href="/dashboard"
            aria-label="Apollo home"
            className="flex min-w-0 items-center gap-3 bg-transparent border-0 p-0 cursor-pointer"
          >
            <ApolloMark size={28} />
            <span className="hidden whitespace-nowrap font-mono text-[9px] uppercase tracking-[0.16em] text-faint xl:inline">
              AI music entertainment system
            </span>
            {route !== "library" && sessionLabel && (
              <Crumb>{sessionLabel}</Crumb>
            )}
          </Link>

          <nav aria-label="Apollo product" className="flex min-w-0 overflow-x-auto gap-1 border border-line p-[3px]">
            {NAV_ROUTES.map((r) => {
              const active = r.id === route;
              return (
                <Link
                  key={r.id}
                  href={r.href}
                  className={
                    "px-3.5 py-1.5 text-xs tracking-[0.02em] " +
                    (active
                      ? "bg-cream text-ink"
                      : "bg-transparent text-mute hover:text-ember-text")
                  }
                >
                  {r.label}
                </Link>
              );
            })}
          </nav>

          <span className="text-[13px] text-mute">{username ?? "guest"}</span>
        </header>
      )}

      <main className="flex flex-1 flex-col">{children}</main>
    </div>
  );
}
