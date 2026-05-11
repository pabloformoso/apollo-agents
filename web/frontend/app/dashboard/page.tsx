"use client";
/**
 * Apollo v2.6.0 — Dashboard (Library).
 *
 * Direct port of the prototype `Dashboard` from
 * docs/design/apollo-claude-design/apollo/project/prototype-screens.jsx.
 *
 * Wires real session data from the existing `listSessions` API (the v2.5.x
 * 9-phase backend) until the API refactor lands. The hero card on the
 * right showcases "last performed" — falls back to the most recent session
 * with phase=complete; if none exist, a static placeholder.
 */
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { listSessions } from "@/lib/api";
import { clearAuth, useAuth } from "@/lib/auth";
import type { SessionState } from "@/lib/types";
import { Shell } from "@/components/ember/Shell";
import {
  ApolloMark,
  Arrow,
  Btn,
  Crumb,
  Stripe,
} from "@/components/ember/primitives";

function fmtDur(min: number | null | undefined): string {
  if (!min) return "?m";
  return min < 60
    ? `${min}m`
    : `${Math.floor(min / 60)}h${min % 60 ? ` ${min % 60}m` : ""}`;
}

export default function DashboardPage() {
  const router = useRouter();
  const { user, hydrated } = useAuth();
  const [sessions, setSessions] = useState<SessionState[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) {
      router.push("/login");
      return;
    }
    let cancelled = false;
    listSessions()
      .then((s) => {
        if (cancelled) return;
        setSessions(s);
      })
      .catch(() => {
        if (cancelled) return;
        clearAuth();
        router.push("/login");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrated, user, router]);

  // Heuristic: hero card highlights the most recent session that has a
  // playlist (a "real" set the user has worked on). Falls back to a
  // placeholder copy when the user has nothing yet.
  const hero = useMemo(() => {
    return (
      sessions.find((s) => s.playlist && s.playlist.length > 0) ?? null
    );
  }, [sessions]);

  function handleCreate() {
    // v2.6.0 — /brief creates the session itself on submit (POST
    // /api/sessions { brief }). The dashboard used to pre-create an
    // empty session and pass its id along, which only left a stranded
    // phase=init row in the user's library. Just navigate.
    router.push("/brief");
  }

  async function handleSignOut() {
    clearAuth();
    router.push("/login");
  }

  const sessionCount = sessions.length;
  const totalDur = useMemo(
    () => sessions.reduce((a, s) => a + (s.duration_min ?? 0), 0),
    [sessions],
  );

  function openHero() {
    if (!hero) return;
    const hasPlaylist = (hero.playlist?.length ?? 0) > 0;
    router.push(hasPlaylist ? `/curate?session=${hero.id}` : `/session/${hero.id}`);
  }

  return (
    <Shell fitViewport username={user?.username ?? null}>
      {/* ────── Hero — the entire page presentation, viewport-sized ───── */}
      <section className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-2 gap-x-[60px] items-end px-[60px] pt-10 pb-10">
        <div>
          <Crumb>tonight · curated for you</Crumb>
          <h1 className="font-display italic font-normal tracking-display-tight leading-[0.95] mt-4 mb-0 text-[clamp(56px,7vw,88px)]">
            What will you<br />make tonight
            <span className="text-ember">?</span>
          </h1>
          <p className="text-base text-mute mt-6 max-w-[380px] leading-[1.55]">
            Tell Apollo what you want to hear and it will assemble, critique,
            and either render it for you — or perform it live.
          </p>
          <div className="flex gap-3 mt-8">
            <Btn onClick={handleCreate}>
              Start a session <Arrow />
            </Btn>
            <Btn kind="ghost" onClick={() => router.push("/catalog")}>
              Browse catalog
            </Btn>
          </div>
          {!loading && sessionCount > 0 && (
            <div className="mt-6">
              <Crumb>
                {`${sessionCount} session${sessionCount === 1 ? "" : "s"} · ${fmtDur(totalDur)} · `}
                <button
                  type="button"
                  onClick={() => router.push("/curate")}
                  className="text-ember hover:underline"
                >
                  open library →
                </button>
              </Crumb>
            </div>
          )}
        </div>

        <div
          onClick={hero ? openHero : undefined}
          className={
            "self-end w-full " + (hero ? "cursor-pointer group" : "")
          }
          role={hero ? "button" : undefined}
          tabIndex={hero ? 0 : undefined}
          onKeyDown={(e) => {
            if (hero && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              openHero();
            }
          }}
        >
          <Stripe
            alpha={0.18}
            className="aspect-[5/4] relative flex items-end p-7 border-line2 transition-colors group-hover:border-ember"
          >
            <span className="absolute top-[18px] left-6">
              <Crumb>{hero ? "last performed · live" : "no sets yet"}</Crumb>
            </span>
            <div>
              <div className="font-display italic text-[clamp(36px,4.5vw,54px)] leading-[0.95] text-cream">
                {hero?.session_name ? (
                  hero.session_name.split(" · ")[0]
                ) : (
                  <>warehouse,<br />4am.</>
                )}
              </div>
              <div className="font-mono text-[11px] text-mute mt-3.5 tracking-mono uppercase">
                {hero
                  ? `${(hero.genre ?? "—").toUpperCase()} · ${fmtDur(
                      hero.duration_min,
                    )} · ${(hero.playlist?.length ?? 0)} TRACKS`
                  : "TECHNO · 120 MIN · 18 TRACKS"}
              </div>
            </div>
          </Stripe>
        </div>
      </section>

      {/* Footer with sign out — minimal and tucked away */}
      <footer className="px-[60px] py-4 border-t border-line flex justify-between items-center">
        <div className="flex items-center gap-3">
          <ApolloMark size={18} />
          <Crumb>v2.6.0 · cinematic</Crumb>
        </div>
        <button
          onClick={handleSignOut}
          className="text-faint text-xs hover:text-ember-text transition-colors"
        >
          Sign out
        </button>
      </footer>
    </Shell>
  );
}
