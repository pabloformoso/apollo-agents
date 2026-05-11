"use client";
/**
 * Apollo v2.6.0 — Brief.
 *
 * Direct port of the prototype `Brief` from
 * docs/design/apollo-claude-design/apollo/project/prototype-screens.jsx.
 *
 * The brief is a single textarea on the right; on the left, three
 * suggestion lines + the hero copy. The user types one sentence and Apollo
 * curates. The "understood as" panel is a live optimistic regex preview
 * (``parseBriefOptimistic``) while typing — the server's authoritative
 * parse (Haiku via ``brief_parser``) replaces it after submit, but by then
 * the user is already on ``/curate`` watching planning stream in.
 *
 * Submit:
 *   1. POSTs the brief to ``/api/sessions { brief }``.
 *   2. Server creates the session, parses the brief, kicks off
 *      planning + critique as a background task.
 *   3. Routes to ``/curate?session=<id>`` immediately so the user sees
 *      streaming progress.
 */
import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createSessionWithBrief } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Shell } from "@/components/ember/Shell";
import { Arrow, Btn, Crumb } from "@/components/ember/primitives";
import { toast } from "@/components/ember/feedback";
import {
  itemVariants,
  listVariants,
  motion,
  pageVariants,
} from "@/components/ember/motion";

const SUGGESTIONS = [
  "30 minutes of lofi for a rainy garden",
  "Ninety-minute techno set, build slowly, peak at minute 60",
  "Sunday brunch, neo-soul, warm and easy",
] as const;

type Parsed = {
  genre: string;
  duration: string;
  mood: string;
  venue: string;
  energy: string;
  tempo: string;
};

/** Optimistic client-side regex preview — runs while the user types so
 *  the "understood as" panel updates live. The server's authoritative
 *  parse (Haiku) takes over on submit and is what the planner actually
 *  consumes. Matches the prototype byte-for-byte. */
function parseBriefOptimistic(text: string): Parsed {
  const t = text.toLowerCase();
  const dur =
    t.match(/(\d+)\s*(min|minute|m)\b/) || t.match(/(\d+)\s*(hour|h)\b/);
  const venueMatch = t.match(
    /(garden|cafe|bar|club|warehouse|office|home|car|gym)/,
  );
  const moodMatch = t.match(
    /(chill|contemplative|warm|dark|intense|easy|peaky|peak|melancholic|euphoric|focus)/,
  );
  const genreMatch = t.match(
    /(lofi|ambient|techno|house|deep house|neo[-\s]?soul|synthwave|jazz|trance|garage|drum and bass|dnb)/,
  );
  return {
    genre: genreMatch ? genreMatch[1] : "—",
    duration: dur ? `${dur[1]} ${dur[2] || "min"}` : "—",
    mood: moodMatch ? moodMatch[1] : "—",
    venue: venueMatch ? venueMatch[1] : "—",
    energy: /peak|build|intens/.test(t) ? "with peak" : "plateau, no peaks",
    tempo: /lofi|ambient/.test(t)
      ? "58–66 BPM"
      : /techno/.test(t)
        ? "126–134 BPM"
        : "auto",
  };
}

export default function BriefPage() {
  const router = useRouter();
  const { user, hydrated } = useAuth();

  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!hydrated) return;
    if (!user) router.push("/login");
  }, [hydrated, user, router]);

  const parsed = useMemo(() => parseBriefOptimistic(text), [text]);

  async function submit() {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      const session = await createSessionWithBrief(text);
      router.push(`/curate?session=${session.id}`);
      // Leave `busy` true through navigation so the button keeps the
      // "Curating…" label until the new route mounts. Re-enabled only on
      // error below.
    } catch (e) {
      toast.error(
        (e as Error).message || "Couldn't start the session — try again.",
      );
      setBusy(false);
    }
  }

  return (
    <Shell username={user?.username ?? null}>
      <motion.div
        className="flex-1 grid grid-cols-1 md:grid-cols-2"
        variants={pageVariants}
        initial="initial"
        animate="animate"
      >
        {/* ── Left: hero + suggestions ── */}
        <section className="px-[60px] py-[60px] flex flex-col justify-center border-r border-line">
          <Crumb>01 · brief</Crumb>
          <h1 className="font-display italic font-normal text-[80px] leading-[0.95] tracking-[-0.03em] mt-2 mb-0">
            One sentence.
            <br />
            That&apos;s all
            <br />I need<span className="text-ember">.</span>
          </h1>
          <p className="text-base text-mute mt-6 max-w-[420px] leading-[1.55]">
            Tell me the genre, the duration, the mood and where you&apos;ll
            listen. I&apos;ll fill the rest in and only ask if I really
            need to.
          </p>

          <motion.div
            className="mt-10 flex flex-col gap-2"
            variants={listVariants}
            initial="initial"
            animate="animate"
          >
            {SUGGESTIONS.map((s) => (
              <motion.button
                key={s}
                variants={itemVariants}
                onClick={() => setText(s)}
                className="bg-transparent border-0 p-0 text-left cursor-pointer
                  font-display italic text-base text-ember-text
                  hover:text-cream transition-colors"
              >
                <span className="text-ember mr-2">›</span>
                &ldquo;{s}&rdquo;
              </motion.button>
            ))}
          </motion.div>
        </section>

        {/* ── Right: textarea + parsed fields + CTA ── */}
        <section className="bg-surf px-[50px] py-10 flex flex-col gap-7">
          <div className="flex-1 flex flex-col gap-[18px]">
            <Crumb tone="ember">your prompt</Crumb>
            <textarea
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="A 30-minute lofi ambient set for a rainy garden afternoon…"
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              }}
              className="bg-transparent border-0 text-cream
                font-display italic text-[32px] leading-[1.25] tracking-[-0.015em]
                resize-none outline-none min-h-[180px] p-0
                placeholder:text-faint"
            />
            <div className="h-px bg-line2" />
          </div>

          <div>
            <Crumb>understood as</Crumb>
            <div className="grid grid-cols-2 gap-3.5 mt-3.5">
              {(
                [
                  ["Genre", parsed.genre],
                  ["Duration", parsed.duration],
                  ["Mood", parsed.mood],
                  ["Venue", parsed.venue],
                  ["Energy", parsed.energy],
                  ["Tempo", parsed.tempo],
                ] as const
              ).map(([k, v]) => (
                <div
                  key={k}
                  className="border-t border-line pt-2"
                >
                  <Crumb>{k}</Crumb>
                  <div
                    className={
                      "font-display italic text-xl mt-0.5 " +
                      (v === "—" ? "text-faint" : "text-ember-text")
                    }
                  >
                    {v}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-between items-center">
            <span className="font-mono text-[11px] text-faint">
              {busy ? "Apollo is curating…" : "⌘ + ↵"}
            </span>
            <Btn
              onClick={submit}
              disabled={busy || !text.trim()}
              className="font-display italic text-lg"
            >
              {busy ? "Curating…" : (<>Curate this set <Arrow /></>)}
            </Btn>
          </div>
        </section>
      </motion.div>
    </Shell>
  );
}
