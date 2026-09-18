"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Arrow, ApolloMark, Crumb } from "@/components/ember/primitives";
import { login } from "@/lib/api";
import { saveAuth } from "@/lib/auth";
import {
  buildAuthorizeUrl,
  CALLBACK_PATH,
  challengeFor,
  createState,
  createVerifier,
  isConfigured as realmConfigured,
  safeReturnTo,
  stashFlow,
} from "@/lib/oidc";

const ROLES = [
  ["01", "Collaborators", "shape the direction"],
  ["02", "Critic", "push the music further"],
  ["03", "Performer", "take the system live"],
] as const;

function SystemArtwork() {
  return (
    <div className="relative mx-auto aspect-square w-full max-w-[600px]" aria-hidden="true">
      <div className="absolute inset-[8%] rounded-full border border-ember/20" />
      <div className="absolute inset-[19%] rounded-full border border-cream/15" />
      <div className="absolute inset-[31%] rounded-full border border-ember/35" />
      <div className="absolute inset-[8%] animate-[spin_28s_linear_infinite] rounded-full border border-transparent border-t-ember/60 border-r-ember/20" />
      <div className="absolute inset-[19%] animate-[spin_18s_linear_infinite_reverse] rounded-full border border-transparent border-b-cream/35 border-l-cream/10" />

      <div className="absolute left-1/2 top-[8%] h-2.5 w-2.5 -translate-x-1/2 rounded-full bg-ember shadow-[0_0_24px_rgba(232,85,58,.75)]" />
      <div className="absolute bottom-[18%] left-[18%] h-2 w-2 rounded-full border border-cream/60 bg-ink" />
      <div className="absolute right-[8%] top-1/2 h-2 w-2 -translate-y-1/2 rounded-full border border-ember bg-ink" />

      <div className="absolute inset-[31%] flex flex-col items-center justify-center rounded-full bg-ink/80 text-center shadow-[0_0_80px_rgba(232,85,58,.09)] backdrop-blur-sm">
        <span className="font-mono text-[9px] uppercase tracking-[0.35em] text-ember">Apollo</span>
        <span className="mt-2 font-display text-[clamp(52px,6vw,92px)] italic leading-none text-cream">MES</span>
        <span className="mt-2 font-mono text-[8px] uppercase tracking-[0.24em] text-faint">AI directed</span>
      </div>

      <span className="absolute left-[7%] top-[28%] font-mono text-[8px] uppercase tracking-[0.22em] text-faint">assemble</span>
      <span className="absolute bottom-[8%] left-1/2 -translate-x-1/2 font-mono text-[8px] uppercase tracking-[0.22em] text-faint">critique</span>
      <span className="absolute right-[3%] top-[31%] font-mono text-[8px] uppercase tracking-[0.22em] text-faint">perform</span>
    </div>
  );
}

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const useRealm = realmConfigured();

  async function signInWithRealm() {
    setError("");
    setLoading(true);
    try {
      const verifier = createVerifier();
      const state = createState();
      const params = new URLSearchParams(window.location.search);
      stashFlow(verifier, state, safeReturnTo(params.get("returnTo")));
      const url = buildAuthorizeUrl({
        challenge: await challengeFor(verifier),
        state,
        redirectUri: window.location.origin + CALLBACK_PATH,
      });
      window.location.assign(url);
    } catch (err) {
      setLoading(false);
      setError((err as Error).message);
    }
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      const response = await login(username, password);
      saveAuth(response.access_token, response.user);
      router.push("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative min-h-screen overflow-x-hidden bg-ink font-sans text-ember-text">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_78%_44%,rgba(232,85,58,.12),transparent_31%),linear-gradient(rgba(255,238,220,.025)_1px,transparent_1px),linear-gradient(90deg,rgba(255,238,220,.025)_1px,transparent_1px)] bg-[length:auto,72px_72px,72px_72px]" />
      <div className="pointer-events-none absolute inset-y-0 left-[43%] hidden w-px bg-line2 lg:block" />

      <header className="absolute inset-x-0 top-0 z-20 flex items-center justify-between px-6 py-6 sm:px-10 lg:px-14 lg:py-8">
        <ApolloMark size={30} />
        <div className="hidden items-center gap-3 sm:flex">
          <span className="h-1.5 w-1.5 rounded-full bg-ember shadow-[0_0_12px_rgba(232,85,58,.85)]" />
          <Crumb tone="mute">music entertainment system · 001</Crumb>
        </div>
      </header>

      <div className="relative z-10 grid min-h-screen lg:grid-cols-[43%_57%]">
        <section className="flex min-h-screen flex-col justify-center px-6 pb-16 pt-28 sm:px-10 lg:px-14 lg:pb-12">
          <div className="w-full max-w-[520px]">
            <Crumb tone="ember">enter apollo</Crumb>
            <h1 className="mt-5 max-w-[510px] font-display text-[clamp(58px,7vw,106px)] italic font-normal leading-[0.86] tracking-[-0.04em] text-cream">
              Sign in to the<br />music system<span className="text-ember">.</span>
            </h1>
            <p className="mt-7 max-w-[430px] text-[15px] leading-7 text-mute">
              Sign in to a place where AI collaborators assemble the music,
              a critic sharpens it, and every session can become a performance.
            </p>

            <div className="mt-10 border-y border-line2 py-7 sm:mt-12">
              {useRealm ? (
                <div>
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <Crumb>secure access</Crumb>
                      <p className="mt-2 text-sm text-mute">Continue with your Apollo identity.</p>
                    </div>
                    <button
                      type="button"
                      onClick={signInWithRealm}
                      disabled={loading}
                      className="group inline-flex min-w-[190px] items-center justify-between gap-5 bg-ember px-5 py-4 text-sm font-medium text-cream transition-colors hover:bg-ember-dark disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {loading ? "Redirecting…" : "Continue to sign in"}
                      <Arrow className="transition-transform group-hover:translate-x-1" />
                    </button>
                  </div>
                  {error && <p role="alert" className="mt-5 font-mono text-[10px] uppercase tracking-mono text-ember">{error}</p>}
                </div>
              ) : (
                <form onSubmit={handleSubmit} className="space-y-6">
                  <label className="grid grid-cols-[28px_1fr] items-end gap-3">
                    <span className="pb-3 font-mono text-[9px] text-ember">01</span>
                    <span className="block">
                      <Crumb>username</Crumb>
                      <input
                        type="text"
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        className="mt-1 w-full border-0 border-b border-line2 bg-transparent px-0 py-2 font-display text-2xl italic text-cream outline-none transition-colors placeholder:text-faint focus:border-ember"
                        autoComplete="username"
                        required
                        autoFocus
                      />
                    </span>
                  </label>
                  <label className="grid grid-cols-[28px_1fr] items-end gap-3">
                    <span className="pb-3 font-mono text-[9px] text-ember">02</span>
                    <span className="block">
                      <Crumb>password</Crumb>
                      <input
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        className="mt-1 w-full border-0 border-b border-line2 bg-transparent px-0 py-2 font-display text-2xl italic text-cream outline-none transition-colors placeholder:text-faint focus:border-ember"
                        autoComplete="current-password"
                        required
                      />
                    </span>
                  </label>
                  {error && <p role="alert" className="font-mono text-[10px] uppercase tracking-mono text-ember">{error}</p>}
                  <div className="flex items-center justify-between gap-4 pt-2">
                    <Link href="/register" className="font-mono text-[10px] uppercase tracking-mono text-faint transition-colors hover:text-cream">
                      New here? Create an account
                    </Link>
                    <button
                      type="submit"
                      disabled={loading || !username.trim() || !password.trim()}
                      className="group inline-flex items-center gap-5 bg-ember px-6 py-3.5 text-sm font-medium text-cream transition-colors hover:bg-ember-dark disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {loading ? "Signing in…" : "Enter Apollo"}
                      <Arrow className="transition-transform group-hover:translate-x-1" />
                    </button>
                  </div>
                </form>
              )}
            </div>

            <div className="mt-7 flex items-center justify-between gap-4 font-mono text-[9px] uppercase tracking-[0.17em] text-faint">
              <span>AI directed</span>
              <span className="h-px flex-1 bg-line" />
              <span>human shaped</span>
            </div>
          </div>
        </section>

        <section className="relative hidden min-h-screen overflow-hidden px-12 pb-10 pt-28 lg:flex lg:flex-col lg:justify-between xl:px-20">
          <div className="absolute inset-0 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_7px,rgba(232,85,58,.055)_7px,rgba(232,85,58,.055)_8px)]" />
          <div className="relative flex items-center justify-between">
            <Crumb tone="ember">the first AI-directed music entertainment system</Crumb>
            <Crumb>signal active</Crumb>
          </div>

          <div className="relative my-4 flex min-h-0 flex-1 items-center justify-center">
            <SystemArtwork />
          </div>

          <div className="relative grid grid-cols-3 border-t border-line2">
            {ROLES.map(([number, title, body]) => (
              <div key={number} className="border-r border-line2 px-4 py-5 first:pl-0 last:border-r-0 last:pr-0 xl:px-6">
                <span className="font-mono text-[9px] text-ember">{number}</span>
                <p className="mt-2 font-display text-2xl italic text-cream">{title}<span className="text-ember">.</span></p>
                <p className="mt-1 text-xs text-mute">{body}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
