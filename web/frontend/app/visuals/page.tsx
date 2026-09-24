"use client";
/**
 * /visuals — the visual lab.
 *
 * The live visuals need a live set to be seen, which makes them hard to
 * design, review or demo. This page drives the SAME ``<VisualLayer>`` the
 * live pages mount from a synthetic track (genre, BPM, key) and an
 * optional audio source, with no session, socket or backend:
 *
 *   - **Beat clock only** — the default; what a viewer sees before its
 *     first deck, and what every scene falls back to.
 *   - **Audio file** — decoded and looped through an AnalyserNode, the
 *     same tap shape ``useLiveSession`` builds on its master bus.
 *   - **Microphone** — play music in the room. Needs a secure context
 *     (HTTPS or localhost), like AudioWorklet; the page says so rather than
 *     failing silently over a tailnet IP.
 *
 * Deliberately not in the nav: it is a workbench, reached by URL.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import VisualLayer from "@/components/VisualLayer";
import type { LiveTrackSummary } from "@/lib/live";

const GENRES = ["healing", "aural", "lofi-ambient", "deep house", "techno", "cyberpunk"];
const KEYS = Array.from({ length: 12 }, (_, i) => [`${i + 1}A`, `${i + 1}B`]).flat();

type Source = "clock" | "file" | "mic";

export default function VisualsLabPage() {
  const [genre, setGenre] = useState("healing");
  const [bpm, setBpm] = useState(64);
  const [key, setKey] = useState("8B");
  const [source, setSource] = useState<Source>("clock");
  const [status, setStatus] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);

  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const stopSourceRef = useRef<(() => void) | null>(null);
  // Beat clock origin. A getter keeps VisualLayer's contract
  // (``audioRef.current.currentTime``) without a React update per frame.
  const t0Ref = useRef(0);
  const audioRef = useRef<{ readonly currentTime: number }>({
    get currentTime() {
      return (performance.now() - t0Ref.current) / 1000;
    },
  });
  useEffect(() => {
    t0Ref.current = performance.now();
  }, [bpm]);

  const track = useMemo<LiveTrackSummary>(
    () => ({
      id: `${genre}--visual-lab`,
      display_name: `${genre} · ${bpm} BPM · ${key}`,
      bpm,
      camelot_key: key,
      beatgrid: { bpm, first_beat_sec: 0 },
    }),
    [genre, bpm, key],
  );

  const ensureAnalyser = useCallback(() => {
    if (!ctxRef.current) ctxRef.current = new AudioContext();
    const ctx = ctxRef.current;
    if (!analyserRef.current) {
      const an = ctx.createAnalyser();
      an.fftSize = 1024;
      an.smoothingTimeConstant = 0.78;
      analyserRef.current = an;
    }
    void ctx.resume();
    return { ctx, an: analyserRef.current };
  }, []);

  const stopSource = useCallback(() => {
    stopSourceRef.current?.();
    stopSourceRef.current = null;
  }, []);

  useEffect(() => () => {
    stopSource();
    void ctxRef.current?.close();
  }, [stopSource]);

  const pickClock = useCallback(() => {
    stopSource();
    setSource("clock");
    setStatus(null);
  }, [stopSource]);

  const onFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      stopSource();
      setStatus(`decoding ${file.name}…`);
      try {
        const { ctx, an } = ensureAnalyser();
        const buf = await ctx.decodeAudioData(await file.arrayBuffer());
        const src = ctx.createBufferSource();
        src.buffer = buf;
        src.loop = true;
        src.connect(an);
        src.connect(ctx.destination);
        src.start();
        t0Ref.current = performance.now();
        stopSourceRef.current = () => {
          try {
            src.stop();
          } catch {
            /* already stopped */
          }
          src.disconnect();
        };
        setSource("file");
        setStatus(`${file.name} — set the BPM to the track's to lock the beat`);
      } catch (err) {
        setStatus(`could not decode: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
    [ensureAnalyser, stopSource],
  );

  const pickMic = useCallback(async () => {
    stopSource();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setStatus("the mic needs HTTPS or localhost — this origin is not a secure context");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
      });
      const { ctx, an } = ensureAnalyser();
      const node = ctx.createMediaStreamSource(stream);
      node.connect(an); // never to the speakers: no feedback loop
      stopSourceRef.current = () => {
        node.disconnect();
        stream.getTracks().forEach((t) => t.stop());
      };
      setSource("mic");
      setStatus("listening to the room");
    } catch (err) {
      setStatus(`mic refused: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [ensureAnalyser, stopSource]);

  const chip = (active: boolean) =>
    `px-3 py-1 rounded-full text-[10px] uppercase tracking-[0.2em] transition-colors ${
      active ? "bg-white text-black" : "text-white/60 hover:text-white"
    }`;

  return (
    <main data-testid="visuals-lab" className="fixed inset-0 z-[60] bg-black">
      <VisualLayer
        audioRef={audioRef}
        analyserRef={source === "clock" ? undefined : analyserRef}
        currentTrack={track}
      />

      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 w-[min(920px,calc(100vw-32px))]">
        {panelOpen ? (
          <div className="rounded-2xl border border-white/10 bg-black/55 backdrop-blur-xl px-5 py-4 flex flex-col gap-3 text-white">
            <div className="flex items-center justify-between">
              <span className="font-mono text-[10px] uppercase tracking-[0.3em] text-white/50">
                visual lab
              </span>
              <button
                className="text-[10px] uppercase tracking-[0.2em] text-white/50 hover:text-white"
                onClick={() => setPanelOpen(false)}
              >
                hide
              </button>
            </div>

            <div className="flex flex-wrap gap-1">
              {GENRES.map((g) => (
                <button key={g} className={chip(genre === g)} onClick={() => setGenre(g)}>
                  {g}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-3 text-[10px] uppercase tracking-[0.2em] text-white/60">
                bpm
                <input
                  data-testid="lab-bpm"
                  type="range"
                  min={50}
                  max={175}
                  value={bpm}
                  onChange={(e) => setBpm(Number(e.target.value))}
                  className="w-48 accent-white"
                />
                <span className="font-mono text-white w-8">{bpm}</span>
              </label>
              <label className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-white/60">
                key
                <select
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  className="bg-transparent border border-white/20 rounded-full px-2 py-1 text-white font-mono text-xs"
                >
                  {KEYS.map((k) => (
                    <option key={k} value={k} className="bg-black">
                      {k}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] uppercase tracking-[0.2em] text-white/40 mr-1">
                hears
              </span>
              <button className={chip(source === "clock")} onClick={pickClock}>
                beat clock
              </button>
              <label className={`${chip(source === "file")} cursor-pointer`}>
                audio file
                <input
                  type="file"
                  accept="audio/*"
                  className="hidden"
                  onChange={(e) => void onFile(e.target.files?.[0])}
                />
              </label>
              <button className={chip(source === "mic")} onClick={() => void pickMic()}>
                microphone
              </button>
              {status ? <span className="text-xs text-white/60 ml-2">{status}</span> : null}
            </div>
          </div>
        ) : (
          <button
            className="mx-auto block rounded-full border border-white/10 bg-black/50 backdrop-blur-md px-4 py-1.5 text-[10px] uppercase tracking-[0.2em] text-white/60 hover:text-white"
            onClick={() => setPanelOpen(true)}
          >
            lab controls
          </button>
        )}
      </div>
    </main>
  );
}
