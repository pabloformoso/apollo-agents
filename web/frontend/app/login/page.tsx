"use client";
/**
 * Apollo v2.6.0 — Login.
 *
 * Ember design system port of the legacy login form. The visual treatment
 * follows the prototype: italic display headline, mono labels, ember
 * accent on the submit button, stripe placeholder on the right pane to
 * mirror the Brief / Curate vocabulary.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login } from "@/lib/api";
import { saveAuth } from "@/lib/auth";
import { ApolloMark, Btn, Crumb, Stripe } from "@/components/ember/primitives";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await login(username, password);
      saveAuth(res.access_token, res.user);
      router.push("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="h-screen overflow-hidden grid grid-cols-1 md:grid-cols-2 bg-ink text-ember-text font-sans">
      {/* ── Left: form ── */}
      <section className="px-[60px] py-10 flex flex-col justify-center">
        <ApolloMark size={28} />
        <Crumb className="mt-8 block">welcome back</Crumb>
        <h1 className="font-display italic font-normal text-[clamp(48px,6vw,80px)] leading-[0.95] tracking-[-0.03em] mt-2">
          Sign in<span className="text-ember">.</span>
        </h1>

        <form
          onSubmit={handleSubmit}
          className="mt-8 flex flex-col gap-5 max-w-[360px]"
        >
          <div className="flex flex-col gap-2">
            <Crumb>username</Crumb>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-transparent border-0 border-b border-line2 px-0 py-2
                font-display italic text-2xl text-cream
                outline-none focus:border-ember transition-colors
                placeholder:text-faint"
              required
              autoFocus
            />
          </div>

          <div className="flex flex-col gap-2">
            <Crumb>password</Crumb>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full bg-transparent border-0 border-b border-line2 px-0 py-2
                font-display italic text-2xl text-cream
                outline-none focus:border-ember transition-colors
                placeholder:text-faint"
              required
            />
          </div>

          {error && (
            <p className="font-mono text-[11px] text-ember uppercase tracking-mono">
              {error}
            </p>
          )}

          <div className="flex justify-between items-center mt-4">
            <Link
              href="/register"
              className="font-mono text-[11px] text-faint uppercase tracking-mono hover:text-ember transition-colors"
            >
              No account · register
            </Link>
            <Btn
              type="submit"
              disabled={loading || !username.trim() || !password.trim()}
              className="font-display italic text-lg"
            >
              {loading ? "Signing in…" : "Enter"}
            </Btn>
          </div>
        </form>
      </section>

      {/* ── Right: stripe poster ── */}
      <Stripe alpha={0.18} className="hidden md:flex border-l border-line p-10 flex-col justify-between overflow-hidden">
        <Crumb tone="ember">apollo · ai dj</Crumb>
        <div>
          <div className="font-display italic text-[clamp(44px,5.5vw,72px)] leading-[0.92] text-cream tracking-[-0.035em]">
            assemble.<br />
            critique.<br />
            perform<span className="text-ember">.</span>
          </div>
          <p className="text-mute text-base mt-5 max-w-[420px] leading-[1.55]">
            One sentence in. A curated set out — render to YouTube or take
            the booth and perform live.
          </p>
        </div>
      </Stripe>
    </div>
  );
}
