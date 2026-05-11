"use client";
/**
 * Apollo v2.6.0 — Register.
 * Mirrors the Login layout — italic display heading + underline-only
 * inputs + ember stripe poster on the right.
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { register } from "@/lib/api";
import { saveAuth } from "@/lib/auth";
import { ApolloMark, Btn, Crumb, Stripe } from "@/components/ember/primitives";

export default function RegisterPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await register(username, email, password);
      saveAuth(res.access_token, res.user);
      router.push("/dashboard");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }

  const fields: ReadonlyArray<{
    label: string;
    value: string;
    set: (v: string) => void;
    type: "text" | "email" | "password";
  }> = [
    { label: "Username", value: username, set: setUsername, type: "text" },
    { label: "Email", value: email, set: setEmail, type: "email" },
    { label: "Password", value: password, set: setPassword, type: "password" },
  ];

  return (
    <div className="h-screen overflow-hidden grid grid-cols-1 md:grid-cols-2 bg-ink text-ember-text font-sans">
      <section className="px-[60px] py-10 flex flex-col justify-center">
        <ApolloMark size={28} />
        <Crumb className="mt-8 block">first time</Crumb>
        <h1 className="font-display italic font-normal text-[clamp(44px,5.5vw,72px)] leading-[0.95] tracking-[-0.03em] mt-2">
          Make an account<span className="text-ember">.</span>
        </h1>

        <form
          onSubmit={handleSubmit}
          className="mt-8 flex flex-col gap-5 max-w-[360px]"
        >
          {fields.map(({ label, value, set, type }) => (
            <div key={label} className="flex flex-col gap-2">
              <Crumb>{label.toLowerCase()}</Crumb>
              <input
                type={type}
                value={value}
                onChange={(e) => set(e.target.value)}
                className="w-full bg-transparent border-0 border-b border-line2 px-0 py-2
                  font-display italic text-2xl text-cream
                  outline-none focus:border-ember transition-colors
                  placeholder:text-faint"
                required
              />
            </div>
          ))}

          {error && (
            <p className="font-mono text-[11px] text-ember uppercase tracking-mono">
              {error}
            </p>
          )}

          <div className="flex justify-between items-center mt-4">
            <Link
              href="/login"
              className="font-mono text-[11px] text-faint uppercase tracking-mono hover:text-ember transition-colors"
            >
              Have an account · sign in
            </Link>
            <Btn
              type="submit"
              disabled={loading || !username.trim() || !password.trim()}
              className="font-display italic text-lg"
            >
              {loading ? "Creating…" : "Create account"}
            </Btn>
          </div>
        </form>
      </section>

      <Stripe alpha={0.18} className="hidden md:flex border-l border-line p-10 flex-col justify-between overflow-hidden">
        <Crumb tone="ember">apollo · ai dj</Crumb>
        <div>
          <div className="font-display italic text-[clamp(40px,5vw,64px)] leading-[0.92] text-cream tracking-[-0.035em]">
            tonight,<br />
            curated<br />
            for you<span className="text-ember">.</span>
          </div>
          <p className="text-mute text-base mt-5 max-w-[420px] leading-[1.55]">
            One sentence in. Apollo assembles, critiques, and performs the
            set — async to YouTube or live in the booth.
          </p>
        </div>
      </Stripe>
    </div>
  );
}
