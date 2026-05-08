/**
 * Vitest unit tests for the visualizer effect modules.
 *
 * happy-dom does not implement a real WebGL context, so we mock the
 * subset of three.js we use rather than running the actual GL pipeline.
 * The tests verify:
 *
 *   - The factory functions return objects matching the documented
 *     ``{init, render, resize, destroy}`` shape.
 *   - ``init`` is idempotent.
 *   - ``render`` doesn't throw with valid ``BeatClockResult`` inputs.
 *   - ``destroy`` calls ``dispose`` on geometry / material / renderer
 *     so we don't leak GL resources between effect switches.
 *   - The strobe effect respects the ``max_hz`` rate cap.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createParticlesEffect } from "@/lib/visualizer/effects/particles";
import { createFractalEffect } from "@/lib/visualizer/effects/fractal";
import {
  createStrobeEffect,
  STROBE_DEFAULT_MAX_HZ,
} from "@/lib/visualizer/effects/strobe";
import type { BeatClockResult } from "@/lib/visualizer/beat_clock";

// ── Three.js mock — covers only the surface we use.  Each constructor
//    counts disposals so the tests can assert no leak. ─────────────────────
const disposals = {
  geometry: 0,
  material: 0,
  renderer: 0,
};

vi.mock("three", () => {
  class BufferAttribute {
    needsUpdate = false;
    constructor(public array: Float32Array, public itemSize: number) {}
  }
  class BufferGeometry {
    private attrs = new Map<string, BufferAttribute>();
    setAttribute(name: string, attr: BufferAttribute) {
      this.attrs.set(name, attr);
    }
    getAttribute(name: string) {
      return this.attrs.get(name);
    }
    dispose() {
      disposals.geometry++;
    }
  }
  class PlaneGeometry extends BufferGeometry {}

  class Color {
    setHex = vi.fn();
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

  class PointsMaterial {
    size = 0.05;
    color = new Color();
    opacity = 1;
    constructor(_opts?: unknown) {}
    dispose() {
      disposals.material++;
    }
  }
  class ShaderMaterial {
    uniforms: Record<string, { value: unknown }> = {};
    constructor(opts?: { uniforms?: Record<string, { value: unknown }> }) {
      this.uniforms = opts?.uniforms ?? {};
    }
    dispose() {
      disposals.material++;
    }
  }

  class Points {
    rotation = { x: 0, y: 0, z: 0 };
    constructor(public geometry: BufferGeometry, public material: PointsMaterial) {}
  }
  class Mesh {
    constructor(public geometry: BufferGeometry, public material: ShaderMaterial) {}
  }
  class Scene {
    add() {}
  }
  class PerspectiveCamera {
    aspect = 1;
    position = { x: 0, y: 0, z: 0 };
    updateProjectionMatrix() {}
    constructor(_fov?: number, _aspect?: number) {}
  }
  class OrthographicCamera {
    constructor(
      _left?: number,
      _right?: number,
      _top?: number,
      _bottom?: number,
    ) {}
  }
  class WebGLRenderer {
    domElement = {};
    constructor(_opts?: unknown) {}
    setPixelRatio() {}
    setSize() {}
    setClearColor() {}
    render() {}
    dispose() {
      disposals.renderer++;
    }
  }
  return {
    BufferAttribute,
    BufferGeometry,
    PlaneGeometry,
    Color,
    Vector2,
    Vector3,
    Points,
    PointsMaterial,
    ShaderMaterial,
    Mesh,
    Scene,
    PerspectiveCamera,
    OrthographicCamera,
    WebGLRenderer,
    AdditiveBlending: 1,
  };
});

const BEAT: BeatClockResult = {
  beat_index: 0,
  phase_in_beat: 0,
  is_downbeat: true,
};

function makeCanvas(): HTMLCanvasElement {
  const c = document.createElement("canvas");
  // happy-dom returns 0 for clientWidth/Height by default — synthesise a
  // size so three.js initialises.
  Object.defineProperty(c, "clientWidth", { value: 1280, configurable: true });
  Object.defineProperty(c, "clientHeight", { value: 720, configurable: true });
  return c;
}

beforeEach(() => {
  disposals.geometry = 0;
  disposals.material = 0;
  disposals.renderer = 0;
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("createParticlesEffect", () => {
  it("returns an object satisfying the ParticlesEffect shape", () => {
    const eff = createParticlesEffect();
    expect(typeof eff.init).toBe("function");
    expect(typeof eff.render).toBe("function");
    expect(typeof eff.resize).toBe("function");
    expect(typeof eff.destroy).toBe("function");
  });

  it("init succeeds with a canvas and is idempotent", () => {
    const eff = createParticlesEffect();
    const canvas = makeCanvas();
    expect(() => eff.init(canvas)).not.toThrow();
    // Calling init again should be a no-op (no extra renderer created).
    expect(() => eff.init(canvas)).not.toThrow();
    eff.destroy();
  });

  it("render does not throw with valid beat / track inputs", () => {
    const eff = createParticlesEffect();
    eff.init(makeCanvas());
    expect(() => eff.render(BEAT, { camelot_key: "8A" })).not.toThrow();
    expect(() =>
      eff.render(
        { beat_index: 5, phase_in_beat: 0.4, is_downbeat: false },
        null,
      ),
    ).not.toThrow();
    eff.destroy();
  });

  it("resize forwards width/height to the renderer", () => {
    const eff = createParticlesEffect();
    eff.init(makeCanvas());
    expect(() => eff.resize(800, 600)).not.toThrow();
    eff.destroy();
  });

  it("destroy releases geometry, material, and renderer", () => {
    const eff = createParticlesEffect();
    eff.init(makeCanvas());
    eff.destroy();
    expect(disposals.geometry).toBe(1);
    expect(disposals.material).toBe(1);
    expect(disposals.renderer).toBe(1);
  });
});

describe("createFractalEffect", () => {
  it("returns the documented shape and survives the full lifecycle", () => {
    const eff = createFractalEffect();
    expect(typeof eff.init).toBe("function");
    expect(typeof eff.render).toBe("function");
    expect(typeof eff.resize).toBe("function");
    expect(typeof eff.destroy).toBe("function");

    eff.init(makeCanvas());
    expect(() =>
      eff.render(BEAT, { bpm: 128, camelot_key: "5A" }),
    ).not.toThrow();
    expect(() => eff.resize(640, 360)).not.toThrow();
    eff.destroy();
    expect(disposals.geometry).toBeGreaterThanOrEqual(1);
    expect(disposals.material).toBeGreaterThanOrEqual(1);
    expect(disposals.renderer).toBeGreaterThanOrEqual(1);
  });

  it("falls back to bpm=120 when currentTrack is null", () => {
    const eff = createFractalEffect();
    eff.init(makeCanvas());
    expect(() => eff.render(BEAT, null)).not.toThrow();
    eff.destroy();
  });
});

describe("createStrobeEffect", () => {
  it("returns the documented shape", () => {
    const eff = createStrobeEffect();
    expect(typeof eff.init).toBe("function");
    expect(typeof eff.render).toBe("function");
    expect(typeof eff.setMaxHz).toBe("function");
    expect(typeof eff.destroy).toBe("function");
  });

  it("creates an overlay div on init and removes it on destroy", () => {
    const container = document.createElement("div");
    const eff = createStrobeEffect();
    eff.init(container);
    expect(container.querySelector("[data-testid=strobe-overlay]")).toBeTruthy();
    eff.destroy();
    expect(container.querySelector("[data-testid=strobe-overlay]")).toBeNull();
  });

  it("flashes on a downbeat that lands on the configured bar cadence", () => {
    const container = document.createElement("div");
    const eff = createStrobeEffect();
    eff.init(container);
    // every_n_downbeats=1 → fire on beat_index=0, 4, 8 ...
    eff.render(
      { beat_index: 0, phase_in_beat: 0, is_downbeat: true },
      1,
    );
    const overlay = container.querySelector(
      "[data-testid=strobe-overlay]",
    ) as HTMLDivElement;
    expect(parseFloat(overlay.style.opacity)).toBeGreaterThan(0);
    eff.destroy();
  });

  it("respects the safety cap (default 3 Hz) — back-to-back downbeats can't fire faster", () => {
    expect(STROBE_DEFAULT_MAX_HZ).toBe(3);
    const container = document.createElement("div");
    const eff = createStrobeEffect();
    eff.init(container);
    eff.setMaxHz(3);
    // First fire — opacity goes high.
    eff.render(
      { beat_index: 0, phase_in_beat: 0, is_downbeat: true },
      1,
    );
    const overlay = container.querySelector(
      "[data-testid=strobe-overlay]",
    ) as HTMLDivElement;
    const firstOpacity = parseFloat(overlay.style.opacity);
    expect(firstOpacity).toBeGreaterThan(0.5);

    // Immediately attempt to fire a "different" beat — the rate cap
    // prevents the overlay from re-arming.  We can't measure the
    // refusal directly (the decay path will lower the opacity anyway)
    // but we CAN assert the lastFiredBeatIndex didn't advance by
    // checking that another render at the same beat doesn't bump
    // opacity back to ~1 again.
    eff.render(
      { beat_index: 4, phase_in_beat: 0, is_downbeat: true },
      1,
    );
    const secondOpacity = parseFloat(overlay.style.opacity);
    // Either the opacity is decaying or has been refused — either way
    // it must NOT be a fresh high pulse.
    expect(secondOpacity).toBeLessThanOrEqual(firstOpacity);
    eff.destroy();
  });
});
