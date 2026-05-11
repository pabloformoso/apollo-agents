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

export const ROUTES = [
  { id: "dashboard", label: "Library", href: "/" },
  { id: "brief", label: "Brief", href: "/brief" },
  { id: "curate", label: "Curate", href: "/curate" },
  { id: "editor", label: "Editor", href: "/editor" },
  { id: "render", label: "Render", href: "/render" },
  { id: "live", label: "Live", href: "/live" },
] as const;

type RouteId = (typeof ROUTES)[number]["id"];

/** Map a Next pathname to one of the canonical route ids. */
function routeIdForPath(pathname: string | null): RouteId {
  if (!pathname || pathname === "/") return "dashboard";
  if (pathname.startsWith("/brief")) return "brief";
  if (pathname.startsWith("/curate")) return "curate";
  if (pathname.startsWith("/editor")) return "editor";
  if (pathname.startsWith("/render")) return "render";
  if (pathname.startsWith("/live")) return "live";
  return "dashboard";
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
};

export function Shell({ children, sessionLabel, username, fitViewport }: ShellProps) {
  const pathname = usePathname();
  const route = routeIdForPath(pathname);
  const hideNav = route === "live";

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
            href="/"
            className="flex items-baseline gap-[18px] bg-transparent border-0 p-0 cursor-pointer"
          >
            <ApolloMark size={28} />
            {route !== "dashboard" && sessionLabel && (
              <Crumb>{sessionLabel}</Crumb>
            )}
          </Link>

          <nav className="flex gap-1 border border-line p-[3px]">
            {ROUTES.map((r) => {
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
