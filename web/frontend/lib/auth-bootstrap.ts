"use client";
/**
 * Apollo v2.6.0 — query-string token hand-off.
 *
 * OBS Browser Sources (and any embedded CEF instance) don't share
 * localStorage with the operator's main browser, so we need a way for a
 * route to receive an auth token via the URL without leaving it in the
 * address bar afterwards.
 *
 * Usage:
 *
 * ```tsx
 * const { bootstrapping } = useAuthQueryBootstrap();
 * if (bootstrapping) return null;     // wait for the reload
 * // …then the page renders normally — useAuth() reads the freshly
 * // persisted token from localStorage on the next mount.
 * ```
 *
 * Flow:
 *   1. Reads `?auth=<jwt>` from the URL.
 *   2. Verifies it against `/api/auth/me` and grabs the user shape that
 *      `useAuth` expects.
 *   3. Persists token + user to localStorage via `saveAuth`.
 *   4. Replaces the URL with the same path minus `?auth=` and reloads —
 *      `useAuth` only reads localStorage on its mount tick, so a
 *      mid-render `saveAuth()` wouldn't be picked up.
 *
 * Returns `{ bootstrapping: true }` while the hand-off is in flight so
 * the caller can render `null` (or a loader) instead of flashing the
 * page's auth-gate redirect to /login.
 */
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { saveAuth } from "./auth";

export function useAuthQueryBootstrap(): { bootstrapping: boolean } {
  const searchParams = useSearchParams();
  const [bootstrapping, setBootstrapping] = useState(
    () => !!searchParams?.get("auth"),
  );

  useEffect(() => {
    const tokenFromUrl = searchParams?.get("auth");
    if (!tokenFromUrl) {
      setBootstrapping(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const u = await fetch(
          `${process.env.NEXT_PUBLIC_API_BASE ?? ""}/api/auth/me`,
          { headers: { Authorization: `Bearer ${tokenFromUrl}` } },
        ).then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)));
        if (cancelled) return;
        saveAuth(tokenFromUrl, u);
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete("auth");
        // location.replace so useAuth's next mount reads the new token.
        // Strip the JWT from the URL first so the address bar / window
        // title doesn't leak it after the reload.
        window.location.replace(cleanUrl.toString());
      } catch {
        if (cancelled) return;
        setBootstrapping(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Intentionally one-shot — the URL is mutated as part of the flow.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { bootstrapping };
}
