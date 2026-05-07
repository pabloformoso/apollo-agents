"use client";
import { useEffect, useState } from "react";
import type { User } from "./types";

const TOKEN_KEY = "apollo_token";
const USER_KEY = "apollo_user";

export function saveAuth(token: string, user: User): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as User) : null;
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

/**
 * Read the auth user from localStorage with a hydration guard.
 *
 * Returns `{ user, hydrated }`:
 *   - `hydrated` is `false` on the SSR pass and the first client render so
 *     the markup matches between server and client (avoids hydration
 *     warnings).
 *   - On the second client render (after `useEffect` runs once) `hydrated`
 *     becomes `true` and `user` reflects the localStorage value.
 *
 * Pages that auth-gate via `if (!user) router.push("/login")` should only
 * act once `hydrated === true`, otherwise they bounce a logged-in user
 * during the brief pre-hydration render where `user` is still null.
 *
 * The single `setState` inside the mount effect is the canonical "is the
 * client hydrated yet" pattern that `react-hooks/set-state-in-effect`
 * doesn't have a cleaner replacement for in React 19 (`useSyncExternalStore`
 * resyncs synchronously on hydration, but the pre-resync render is still
 * observable by sibling effects, which would auth-redirect spuriously).
 */
export function useAuth(): { user: User | null; hydrated: boolean } {
  const [state, setState] = useState<{ user: User | null; hydrated: boolean }>(
    { user: null, hydrated: false },
  );
  useEffect(() => {
    // One-shot hydration sync — reads localStorage exactly once on mount;
    // empty deps mean no cascading renders are possible. This is the
    // canonical "is the client hydrated yet" pattern that
    // `react-hooks/set-state-in-effect` doesn't have a cleaner replacement
    // for in React 19 (`useSyncExternalStore` resyncs synchronously on
    // hydration, but the pre-resync render is still observable by sibling
    // effects, which would auth-redirect spuriously).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setState({ user: getUser(), hydrated: true });
  }, []);
  return state;
}
