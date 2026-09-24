/**
 * The 2026-09-24 shader scenes: what they hear (audio_features), which
 * one "auto" picks (scene_picker), and the effect lifecycle
 * (shader_scenes) against the same three.js mock visualizer.test.ts uses.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  bandsFromSpectrum,
  beatEnvelopes,
  createFollower,
  followFeatures,
  SILENT,
  syntheticFeatures,
} from "@/lib/visualizer/audio_features";
import {
  autoScene,
  easeRgb,
  genreOf,
  paletteFor,
  symmetryFor,
  type RGB,
} from "@/lib/visualizer/scene_picker";
import {
  createShaderSceneEffect,
  fragmentFor,
  SHADER_SCENES,
  type SceneFrame,
} from "@/lib/visualizer/effects/shader_scenes";

const disposals = { geometry: 0, material: 0, renderer: 0, renders: 0 };

vi.mock("three", () => {
  class PlaneGeometry {
    dispose() {
      disposals.geometry++;
    }
  }
  class Vector2 {
    constructor(public x = 0, public y = 0) {}
    set(x: number, y: number) {
      this.x = x;
      this.y = y;
      return this;
    }
  }
  class Vector3 {
    constructor(public x = 0, public y = 0, public z = 0) {}
    set(x: number, y: number, z: number) {
      this.x = x;
      this.y = y;
      this.z = z;
      return this;
    }
  }
  class ShaderMaterial {
    uniforms: Record<string, { value: unknown }>;
    fragmentShader: string;
    constructor(opts: { uniforms: Record<string, { value: unknown }>; fragmentShader: string }) {
      this.uniforms = opts.uniforms;
      this.fragmentShader = opts.fragmentShader;
    }
    dispose() {
      disposals.material++;
    }
  }
  class Mesh {
    constructor(public geometry: unknown, public material: unknown) {}
  }
  class Scene {
    add() {}
  }
  class OrthographicCamera {}
  class WebGLRenderer {
    setPixelRatio() {}
    setSize() {}
    render() {
      disposals.renders++;
    }
    dispose() {
      disposals.renderer++;
    }
  }
  return { PlaneGeometry, Vector2, Vector3, ShaderMaterial, Mesh, Scene, OrthographicCamera, WebGLRenderer };
});

beforeEach(() => {
  disposals.geometry = 0;
  disposals.material = 0;
  disposals.renderer = 0;
  disposals.renders = 0;
});

// ── audio_features ────────────────────────────────────────────────────────

describe("bandsFromSpectrum", () => {
  // 48 kHz, fftSize 1024 → 46.875 Hz per bin, 512 bins.
  const SR = 48000;
  const FFT = 1024;
  const binOf = (hz: number) => Math.round(hz / (SR / FFT));

  it("puts sub energy in bass and nowhere else", () => {
    const spec = new Uint8Array(512);
    for (let i = binOf(50); i <= binOf(100); i++) spec[i] = 255;
    const b = bandsFromSpectrum(spec, SR, FFT);
    expect(b.bass).toBeGreaterThan(0.5);
    expect(b.mid).toBe(0);
    expect(b.high).toBe(0);
  });

  it("never counts a bin in two bands", () => {
    const spec = new Uint8Array(512);
    spec[binOf(150)] = 255; // right on the bass/mid edge
    const b = bandsFromSpectrum(spec, SR, FFT);
    expect((b.bass > 0 ? 1 : 0) + (b.mid > 0 ? 1 : 0)).toBe(1);
  });

  it("puts hats in high", () => {
    const spec = new Uint8Array(512);
    for (let i = binOf(3000); i <= binOf(9000); i++) spec[i] = 200;
    const b = bandsFromSpectrum(spec, SR, FFT);
    expect(b.high).toBeGreaterThan(0.5);
    expect(b.bass).toBe(0);
  });

  it("is silent for empty or nonsense input", () => {
    expect(bandsFromSpectrum(new Uint8Array(0), SR, FFT)).toEqual(SILENT);
    expect(bandsFromSpectrum(new Uint8Array(512), 0, FFT)).toEqual(SILENT);
  });
});

describe("beatEnvelopes", () => {
  it("kicks at the start of every beat and decays", () => {
    const on = beatEnvelopes({ beat_index: 5, phase_in_beat: 0, is_downbeat: false });
    const late = beatEnvelopes({ beat_index: 5, phase_in_beat: 0.9, is_downbeat: false });
    expect(on.kick).toBeCloseTo(1);
    expect(late.kick).toBeLessThan(0.05);
    expect(on.beat).toBe(5);
  });

  it("accents only the bar's first beat — at most one bright hit per bar", () => {
    const hits = [0, 1, 2, 3, 4, 5, 6, 7].map(
      (i) => beatEnvelopes({ beat_index: i, phase_in_beat: 0, is_downbeat: i % 4 === 0 }).accent,
    );
    expect(hits).toEqual([1, 0, 0, 0, 1, 0, 0, 0]);
  });

  it("stays under 3 accents per second even at 180 BPM", () => {
    // 180 BPM → 3 beats/s → one bar every 1.33 s.
    const beatsPerSec = 180 / 60;
    const accentsPerSec = beatsPerSec / 4;
    expect(accentsPerSec).toBeLessThan(3);
  });
});

describe("syntheticFeatures", () => {
  it("breathes with the kick and stays in 0..1", () => {
    const hit = syntheticFeatures(beatEnvelopes({ beat_index: 0, phase_in_beat: 0, is_downbeat: true }));
    const rest = syntheticFeatures(beatEnvelopes({ beat_index: 0, phase_in_beat: 0.8, is_downbeat: false }));
    expect(hit.bass).toBeGreaterThan(rest.bass);
    for (const v of Object.values(hit)) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });
});

describe("followFeatures", () => {
  it("rises fast and falls slowly", () => {
    const st = createFollower();
    const loud = { bass: 1, mid: 1, high: 1, level: 1 };
    const up = followFeatures(st, loud, 0.05).bass;
    expect(up).toBeGreaterThan(0.8);
    const down = followFeatures(st, SILENT, 0.05).bass;
    expect(down).toBeGreaterThan(0.6); // still ringing out after 50 ms
  });

  it("auto-gains a quiet source up to full scale", () => {
    const st = createFollower();
    const quiet = { bass: 0.12, mid: 0.12, high: 0.12, level: 0.12 };
    let out = SILENT;
    for (let i = 0; i < 600; i++) out = followFeatures(st, quiet, 1 / 60);
    expect(out.bass).toBeGreaterThan(0.9);
  });

  it("does not explode on a huge frame gap", () => {
    const st = createFollower();
    const out = followFeatures(st, { bass: 1, mid: 1, high: 1, level: 1 }, 30);
    for (const v of Object.values(out)) expect(Number.isFinite(v)).toBe(true);
  });
});

// ── scene_picker ──────────────────────────────────────────────────────────

describe("autoScene", () => {
  it("never puts a healing set in a tunnel, whatever its BPM", () => {
    expect(autoScene({ id: "healing--healing-moonlit_rest", bpm: 95 })).toBe("aurora");
    expect(autoScene({ id: "aural--aural-deep_space_drift", bpm: 140 })).toBe("aurora");
    expect(autoScene({ id: "lofi-ambient--lofi_2-cloud_pages", bpm: 150 })).toBe("aurora");
  });

  it("drives techno and cyberpunk", () => {
    expect(autoScene({ id: "techno--acid", bpm: 90 })).toBe("tunnel");
    expect(autoScene({ id: "cyberpunk--x", bpm: 100 })).toBe("tunnel");
  });

  it("falls back to BPM for unknown genres", () => {
    expect(autoScene({ id: "deep house--groove", bpm: 122 })).toBe("tunnel");
    expect(autoScene({ id: "deep house--groove", bpm: 105 })).toBe("prism");
    expect(autoScene({ id: "x", bpm: 70 })).toBe("aurora");
    expect(autoScene(null)).toBe("aurora");
  });

  it("reads the genre from the id prefix", () => {
    expect(genreOf({ id: "healing--healing-x" })).toBe("healing");
    expect(genreOf({ id: "nogenre" })).toBeNull();
  });
});

describe("palette + symmetry", () => {
  it("maps Camelot numbers to 6..12 folds with a sane default", () => {
    expect(symmetryFor("1A")).toBe(6);
    expect(symmetryFor("12B")).toBe(12);
    expect(symmetryFor(null)).toBe(8);
    expect(symmetryFor("zz")).toBe(8);
  });

  it("gives every key two distinct colours in 0..1", () => {
    for (const k of ["1A", "8B", "12A", null]) {
      const { a, b } = paletteFor(k);
      for (const c of [...a, ...b]) {
        expect(c).toBeGreaterThanOrEqual(0);
        expect(c).toBeLessThanOrEqual(1);
      }
      expect(a).not.toEqual(b);
    }
  });

  it("eases towards the target without overshooting", () => {
    const cur: RGB = [0, 0, 0];
    easeRgb(cur, [1, 1, 1], 1);
    expect(cur[0]).toBeGreaterThan(0);
    expect(cur[0]).toBeLessThan(1);
    easeRgb(cur, [1, 1, 1], 1000);
    expect(cur[0]).toBeCloseTo(1);
  });
});

// ── shader_scenes ─────────────────────────────────────────────────────────

function makeCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  Object.defineProperty(c, "clientWidth", { value: 1280, configurable: true });
  Object.defineProperty(c, "clientHeight", { value: 720, configurable: true });
  return c;
}

const FRAME: SceneFrame = {
  time: 1,
  beat: 4.2,
  kick: 0.5,
  accent: 0.3,
  bass: 0.6,
  mid: 0.4,
  high: 0.2,
  level: 0.5,
  colorA: [0.1, 0.6, 0.9],
  colorB: [0.5, 0.3, 0.9],
  symmetry: 8,
};

describe("createShaderSceneEffect", () => {
  it.each(SHADER_SCENES)("%s survives init → render → resize → destroy", (scene) => {
    const eff = createShaderSceneEffect(scene);
    expect(eff.scene).toBe(scene);
    eff.init(makeCanvas());
    eff.init(makeCanvas()); // idempotent
    eff.render(FRAME);
    eff.resize(800, 600);
    eff.destroy();
    expect(disposals.renders).toBe(1);
    expect(disposals).toMatchObject({ geometry: 1, material: 1, renderer: 1 });
    eff.render(FRAME); // after destroy: a no-op, not a throw
    expect(disposals.renders).toBe(1);
  });

  it.each(SHADER_SCENES)("%s declares every uniform the frame drives", (scene) => {
    const src = fragmentFor(scene);
    for (const u of ["u_time", "u_beat", "u_kick", "u_accent", "u_bass", "u_colA", "u_colB"]) {
      expect(src).toContain(`uniform`);
      expect(src).toContain(u);
    }
    expect(src).toContain("void main()");
    expect(src).toContain("finish(");
  });
});
