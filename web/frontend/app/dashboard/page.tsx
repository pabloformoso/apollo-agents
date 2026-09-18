"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { coverUrl, getCatalog, listSessions } from "@/lib/api";
import { clearAuth, useAuth } from "@/lib/auth";
import type { SessionState, Track } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import { DashboardPlayer } from "@/components/ember/DashboardPlayer";
import { ApolloMark, Arrow, Btn, Crumb, Stripe } from "@/components/ember/primitives";

function fmtDur(min: number | null | undefined): string {
  if (!min) return "—";
  return min < 60 ? `${min}m` : `${Math.floor(min / 60)}h${min % 60 ? ` ${min % 60}m` : ""}`;
}

function fmtDate(raw: string): string {
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return "recently";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(date);
}

function artworkFor(track: Track | undefined): string | null {
  if (!track) return null;
  if (track.cover_url) return coverUrl(track.id);
  return track.suno?.cover_url ?? null;
}

const MODULES = [
  {
    id: "catalog",
    href: "/catalog",
    eyebrow: "library",
    title: "Catalog",
    body: "Browse the tracks Apollo already knows.",
    mark: "01",
    className: "md:col-span-2",
  },
  {
    id: "generations",
    href: "/generations",
    eyebrow: "studio",
    title: "Generate music",
    body: "Write a brief, make a take, keep the one that lands.",
    mark: "02",
    className: "",
  },
  {
    id: "sessions",
    href: "/brief",
    eyebrow: "sessions",
    title: "Build a session",
    body: "Give Apollo one sentence and let the collaborators shape the set.",
    mark: "03",
    className: "",
  },
  {
    id: "algorave",
    href: "/algorave",
    eyebrow: "performance",
    title: "Algorave",
    body: "Live code a room with the AI mind at the controls.",
    mark: "04",
    className: "md:col-span-2",
  },
] as const;

export default function DashboardPage() {
  const router = useRouter();
  const { user, hydrated } = useAuth();
  const [sessions, setSessions] = useState<SessionState[]>([]);
  const [catalogTracks, setCatalogTracks] = useState<Track[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.push("/login");
      return;
    }
    let cancelled = false;
    Promise.allSettled([listSessions(), getCatalog()]).then(([sessionResult, catalogResult]) => {
      if (cancelled) return;
      if (sessionResult.status === "fulfilled") setSessions(sessionResult.value);
      else {
        clearAuth();
        router.push("/login");
        return;
      }
      if (catalogResult.status === "fulfilled" && !Array.isArray(catalogResult.value)) {
        setCatalogTracks(catalogResult.value.tracks ?? []);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, router]);

  const catalogById = useMemo(
    () => new Map(catalogTracks.map((track) => [track.id, track])),
    [catalogTracks],
  );
  const completedSessions = useMemo(
    () => sessions.filter((session) => (session.playlist?.length ?? 0) > 0),
    [sessions],
  );
  const hero = completedSessions[0] ?? null;
  const heroTrack = hero ? catalogById.get(hero.playlist[0]?.id) : undefined;
  const heroArtwork = artworkFor(heroTrack);
  const totalDuration = sessions.reduce((sum, session) => sum + (session.duration_min ?? 0), 0);

  function openSession(session: SessionState) {
    router.push(session.playlist?.length ? `/curate?session=${session.id}` : `/session/${session.id}`);
  }

  return (
    <Shell username={user?.username ?? null}>
      <main className="mx-auto w-full max-w-screen-2xl flex-1 px-4 pb-32 pt-8 sm:px-8 lg:px-12">
        <section className="grid gap-8 lg:grid-cols-[1.05fr_.95fr] lg:items-end">
          <div className="max-w-2xl">
            <Crumb tone="ember">apollo · ai music entertainment system</Crumb>
            <h1 className="mt-4 font-display text-[clamp(50px,7vw,96px)] italic leading-[.9] tracking-display-tight">
              What will you<br />make tonight<span className="text-ember">?</span>
            </h1>
            <p className="mt-6 max-w-lg text-base leading-relaxed text-mute">
              A place to discover, generate and perform. Apollo keeps the tools together so you can get to the music faster.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Btn onClick={() => router.push("/brief")}>Start a session <Arrow /></Btn>
              <Btn kind="ghost" onClick={() => router.push("/catalog")}>Browse catalog</Btn>
            </div>
          </div>

          <button
            type="button"
            onClick={() => hero && openSession(hero)}
            disabled={!hero}
            className="group relative aspect-[5/4] min-h-[260px] overflow-hidden border border-line2 text-left disabled:cursor-default"
            data-testid="dashboard-featured"
          >
            {heroArtwork ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={heroArtwork} alt="" className="absolute inset-0 h-full w-full object-cover opacity-65 transition duration-500 group-hover:scale-105" />
            ) : (
              <Stripe alpha={0.2} className="absolute inset-0 h-full w-full border-0" />
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-ink via-ink/25 to-transparent" />
            <span className="absolute left-5 top-5"><Crumb tone="cream">{hero ? "last session" : "apollo home"}</Crumb></span>
            <div className="absolute inset-x-5 bottom-5">
              <h2 className="font-display text-4xl italic leading-none text-cream sm:text-5xl">
                {hero?.session_name?.split(" · ")[0] ?? "Make something"}<span className="text-ember">.</span>
              </h2>
              <p className="mt-3 font-mono text-[10px] uppercase tracking-mono text-cream/75">
                {hero ? `${hero.genre ?? "open format"} · ${fmtDur(hero.duration_min)} · ${hero.playlist.length} tracks` : "Your next session starts here"}
              </p>
            </div>
          </button>
        </section>

        <section className="mt-14" aria-labelledby="modules-heading">
          <div className="mb-4 flex items-end justify-between">
            <div>
              <Crumb>apollo modules</Crumb>
              <h2 id="modules-heading" className="mt-2 font-display text-3xl italic">Choose a room<span className="text-ember">.</span></h2>
            </div>
            {!loading && sessions.length > 0 && <Crumb tone="mute">{sessions.length} sessions · {fmtDur(totalDuration)} total</Crumb>}
          </div>
          <div className="grid auto-rows-fr grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {MODULES.map((module) => (
              <button
                key={module.id}
                type="button"
                onClick={() => router.push(module.href)}
                className={`group relative min-h-[148px] overflow-hidden border border-line2 bg-surf p-5 text-left transition-colors hover:border-ember ${module.className}`}
                data-testid={module.id === "algorave" ? "algorave-entry" : `dashboard-module-${module.id}`}
              >
                <span className="font-mono text-[10px] tracking-mono text-ember">{module.mark} · {module.eyebrow}</span>
                <h3 className="mt-8 font-display text-3xl italic leading-none text-cream">{module.title}<span className="text-ember">.</span></h3>
                <p className="mt-2 max-w-xs text-sm leading-relaxed text-mute">{module.body}</p>
                <span className="absolute right-5 top-5 text-lg text-faint transition-colors group-hover:text-ember">↗</span>
              </button>
            ))}
          </div>
        </section>

        <section className="mt-14" aria-labelledby="recent-heading">
          <div className="mb-4 flex items-end justify-between">
            <div>
              <Crumb>your library</Crumb>
              <h2 id="recent-heading" className="mt-2 font-display text-3xl italic">Recent sessions<span className="text-ember">.</span></h2>
            </div>
            {completedSessions.length > 0 && <button type="button" onClick={() => router.push(`/curate?session=${encodeURIComponent(completedSessions[0].id)}`)} className="font-mono text-[10px] uppercase tracking-mono text-ember hover:underline">Open latest →</button>}
          </div>
          {completedSessions.length === 0 ? (
            <div className="border border-dashed border-line2 px-5 py-8 text-sm text-mute">
              No sessions yet. Start with one sentence and Apollo will build the first room with you.
            </div>
          ) : (
            <div className="divide-y divide-line2 border-y border-line2">
              {completedSessions.slice(0, 4).map((session, index) => {
                const track = catalogById.get(session.playlist[0]?.id);
                const image = artworkFor(track);
                return (
                  <button key={session.id} type="button" onClick={() => openSession(session)} className="group flex w-full items-center gap-4 py-4 text-left hover:bg-surf/60" data-testid="dashboard-recent-session">
                    <span className="w-6 font-mono text-xs text-faint">{String(index + 1).padStart(2, "0")}</span>
                    <div className="h-12 w-16 shrink-0 overflow-hidden border border-line2 bg-surf">
                      {image ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={image} alt="" className="h-full w-full object-cover" />
                      ) : <Stripe alpha={0.15} className="h-full w-full border-0" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-display text-xl italic text-cream">{session.session_name ?? "Untitled session"}</p>
                      <p className="mt-1 font-mono text-[10px] uppercase tracking-mono text-mute">{session.genre ?? "open format"} · {fmtDur(session.duration_min)} · {session.playlist.length} tracks</p>
                    </div>
                    <span className="hidden font-mono text-[10px] uppercase tracking-mono text-faint sm:block">{fmtDate(session.created_at)}</span>
                    <span className="px-2 text-lg text-faint transition-colors group-hover:text-ember">→</span>
                  </button>
                );
              })}
            </div>
          )}
        </section>

        <footer className="mt-14 flex items-center justify-between border-t border-line bg-ink/95 py-5 backdrop-blur-md lg:fixed lg:inset-x-0 lg:bottom-[68px] lg:z-30 lg:px-12">
          <div className="flex items-center gap-3"><ApolloMark size={18} /><Crumb>music, with collaborators</Crumb></div>
          <button type="button" onClick={() => { clearAuth(); router.push("/login"); }} className="text-xs text-faint transition-colors hover:text-ember-text">Sign out</button>
        </footer>
      </main>
      <DashboardPlayer />
    </Shell>
  );
}
