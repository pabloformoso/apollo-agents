"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/ember/Shell";
import { MainLlmPanel } from "@/components/ember/MainLlmPanel";
import { AceServicePanel } from "@/components/ember/AceServicePanel";

/**
 * Two residents of the shared GPU, two panels: the main LLM (everything Apollo
 * thinks with, the Algorave Mind included) and ACE (the song generator).
 */
export default function SettingsPage() {
  const { user, hydrated } = useAuth();
  const router = useRouter();
  useEffect(() => { if (hydrated && !user) router.push("/login"); }, [hydrated, user, router]);
  if (!user) return null;
  return <Shell username={user.username}><main className="mx-auto w-full max-w-4xl space-y-6 px-4 py-8">
    <h1 className="text-3xl">Settings</h1>
    <p className="text-mute">Services and model configuration. Credentials and server addresses remain on the server.</p>
    <MainLlmPanel />
    <section aria-label="ACE generation service" className="space-y-3"><h2 className="text-lg">ACE · Music generation</h2><AceServicePanel /></section>
  </main></Shell>;
}
