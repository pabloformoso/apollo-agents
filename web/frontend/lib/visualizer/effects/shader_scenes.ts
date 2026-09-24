/**
 * shader_scenes — the audio-reactive fullscreen scenes (aurora, prism,
 * tunnel, pulse).
 *
 * One three.js quad, one fragment shader per scene, one shared uniform
 * contract and one shared "finish" pass (ACES tone map, vignette, film
 * grain) so the four read as a family. Everything that moves is driven by
 * a ``SceneFrame`` the caller builds each rAF: the beat envelopes from
 * ``audio_features.beatEnvelopes``, the smoothed bands from the master-bus
 * analyser, and the key palette eased between tracks.
 *
 * Safety: no scene flashes the whole frame on the beat. ``kick`` (every
 * beat) only moves thin lines and small areas; the only large-area
 * brightening is ``accent``, once per bar — see audio_features.ts.
 *
 * Cost: one quad, ≤3 fbm evaluations per pixel, pixel ratio capped at
 * 1.5. The broadcast browser shares its GPU with the LLM on jarvis.
 */
import * as THREE from "three";

import type { RGB, ShaderScene } from "../scene_picker";

export interface SceneFrame {
  /** Seconds since the effect started (monotonic). */
  time: number;
  /** Continuous beat position. */
  beat: number;
  kick: number;
  accent: number;
  bass: number;
  mid: number;
  high: number;
  level: number;
  colorA: RGB;
  colorB: RGB;
  /** Kaleidoscope folds (prism only). */
  symmetry: number;
}

export interface ShaderSceneEffect {
  readonly scene: ShaderScene;
  init(canvas: HTMLCanvasElement): void;
  render(frame: SceneFrame): void;
  resize(width: number, height: number): void;
  destroy(): void;
}

const VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
  }
`;

const COMMON = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform vec2 u_res;
  uniform float u_time;
  uniform float u_beat;
  uniform float u_kick;
  uniform float u_accent;
  uniform float u_bass;
  uniform float u_mid;
  uniform float u_high;
  uniform float u_level;
  uniform vec3 u_colA;
  uniform vec3 u_colB;
  uniform float u_sym;

  float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
  }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
               mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
  }
  float fbm(vec2 p) {
    float v = 0.0, a = 0.5;
    mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
    for (int i = 0; i < 5; i++) { v += a * noise(p); p = m * p; a *= 0.5; }
    return v;
  }
  mat2 rot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }
  vec2 centered() { return (vUv - 0.5) * vec2(u_res.x / max(1.0, u_res.y), 1.0); }
  vec3 aces(vec3 x) {
    return clamp((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0.0, 1.0);
  }
  vec3 finish(vec3 col, vec2 uv) {
    float vig = smoothstep(1.25, 0.2, length(uv * vec2(0.8, 1.0)));
    col *= mix(0.35, 1.0, vig);
    col = aces(col);
    col += (hash(gl_FragCoord.xy + fract(u_time * 61.0)) - 0.5) * 0.04;
    return col;
  }
`;

/** Slow light: domain-warped nebula with aurora curtains. Healing, ambient. */
const AURORA = /* glsl */ `
  void main() {
    vec2 uv = centered();
    float t = u_time * 0.035 + u_beat * 0.004;
    vec2 p = uv * 1.4;
    vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3) - t));
    vec2 r = vec2(fbm(p + 3.0 * q + vec2(1.7, 9.2) + t * 1.4),
                  fbm(p + 3.0 * q + vec2(8.3, 2.8) - t));
    float f = fbm(p + 3.0 * r);

    // Near-black ground; the light lives only in the ridges of the warp.
    float veins = pow(smoothstep(0.28, 0.82, f), 1.9);
    vec3 col = u_colA * 0.025;
    col += u_colA * veins * (1.9 + 0.6 * u_bass);
    col += u_colB * pow(smoothstep(0.5, 1.15, length(r)), 2.5) * veins * 1.6;

    // Curtains: tall, faint, drifting — the mids lift them.
    float curtain = pow(fbm(vec2(uv.x * 2.4 + t * 3.0, uv.y * 0.3 - t)), 4.0) * 2.2;
    curtain *= smoothstep(-0.7, 0.6, uv.y);
    col += u_colB * curtain * (0.25 + 0.45 * u_mid);

    col *= 0.85 + 0.15 * u_accent;
    col += u_colB * 0.04 * u_high * veins;
    gl_FragColor = vec4(finish(col, uv), 1.0);
  }
`;

/** Geometry: kaleidoscope folded from flowing noise. Mid-tempo grooves. */
const PRISM = /* glsl */ `
  void main() {
    vec2 uv = centered();
    float r = length(uv);
    float a = atan(uv.y, uv.x) + u_time * 0.03;
    float sector = 6.2831853 / max(3.0, u_sym);
    a = mod(a, sector);
    a = abs(a - sector * 0.5);
    vec2 p = vec2(cos(a), sin(a)) * r;
    p *= 2.3 - 0.25 * u_bass;
    p += vec2(u_time * 0.04, u_beat * 0.025);

    float f = fbm(p * 1.4 + fbm(p * 2.0 + u_time * 0.05));
    float lines = pow(1.0 - abs(sin(f * 16.0 - u_beat * 1.2)), 14.0);

    vec3 col = mix(u_colA, u_colB, f) * pow(f, 2.4) * 0.9;
    col += mix(u_colB, vec3(1.0), 0.35) * lines * (0.55 + 0.6 * u_kick + 0.3 * u_high);
    col *= smoothstep(1.2, 0.05, r);
    col += u_colA * 0.35 * exp(-r * 7.0) * (0.3 + 0.5 * u_level);
    col *= 1.0 + 0.15 * u_accent;
    gl_FragColor = vec4(finish(col, uv), 1.0);
  }
`;

/** Motion towards the viewer: ring tunnel, chromatic split on the bar. */
const TUNNEL = /* glsl */ `
  vec3 scene(vec2 uv) {
    float r = max(length(uv), 0.015);
    float a = atan(uv.y, uv.x);
    float z = 0.42 / r + u_beat * 0.5;
    // Line widths measured in SCREEN units (dz/dr = 0.42/r^2), so a ring
    // near the edge is as fine as one near the vanishing point.
    float ringD = abs(fract(z) - 0.5) * r * r / 0.42;
    float ring = exp(-pow(ringD * 90.0, 2.0));
    float seg = abs(fract(a / 6.2831853 * 12.0) - 0.5) * (6.2831853 / 12.0) * r;
    float spokes = exp(-pow(seg * 160.0, 2.0)) * 0.35;
    float depthFade = smoothstep(0.02, 0.35, r) * smoothstep(1.6, 0.4, r);
    vec3 c = mix(u_colA, u_colB, 0.5 + 0.5 * sin(z * 0.7));
    vec3 col = c * (ring * (0.9 + 1.6 * u_kick) + spokes * (0.3 + 0.8 * u_high)) * depthFade;
    col += c * 0.05 * fbm(vec2(a * 2.0, z * 0.5)) * depthFade;
    col += u_colB * exp(-r * 10.0) * (0.15 + 0.5 * u_bass);
    return col;
  }
  void main() {
    vec2 uv = centered();
    uv = rot(u_beat * 0.015 + sin(u_time * 0.1) * 0.3) * uv;
    uv *= 1.0 - 0.04 * u_kick;
    float ca = 0.003 + 0.012 * u_accent;
    vec3 col = vec3(scene(uv * (1.0 + ca)).r, scene(uv).g, scene(uv * (1.0 - ca)).b);
    gl_FragColor = vec4(finish(col, uv), 1.0);
  }
`;

/**
 * The strobe, redone: a light source that breathes with the sub and
 * shockwaves — one per bar, a fainter one per beat — instead of a white
 * frame. The bar accent is a coloured bloom, never white.
 */
const PULSE = /* glsl */ `
  void main() {
    vec2 uv = centered();
    float r = length(uv);
    float barPhase = fract(u_beat / 4.0);
    float beatPhase = fract(u_beat);
    float barWave = exp(-pow((r - barPhase * 1.4) * 22.0, 2.0)) * pow(1.0 - barPhase, 1.5);
    float barTrail = exp(-pow((r - barPhase * 1.4) * 5.0, 2.0)) * (1.0 - barPhase) * 0.25;
    float beatWave = exp(-pow((r - beatPhase * 0.8) * 40.0, 2.0)) * (1.0 - beatPhase) * 0.45;
    float haze = fbm(uv * 2.5 + vec2(u_time * 0.06, -u_time * 0.04));

    vec3 tint = mix(u_colA, u_colB, 0.5 + 0.5 * sin(u_time * 0.15));
    vec3 col = u_colA * 0.05 * haze * haze;
    col += u_colA * exp(-r * 4.0) * (0.2 + 0.6 * u_bass);
    col += tint * (barWave * 2.6 + barTrail * 1.4 + beatWave * (0.8 + 0.8 * u_high));
    col += u_colB * u_accent * 0.18 * exp(-r * 2.0);
    gl_FragColor = vec4(finish(col, uv), 1.0);
  }
`;

const FRAGMENTS: Record<ShaderScene, string> = {
  aurora: AURORA,
  prism: PRISM,
  tunnel: TUNNEL,
  pulse: PULSE,
};

export const SHADER_SCENES = Object.keys(FRAGMENTS) as ShaderScene[];

export function fragmentFor(scene: ShaderScene): string {
  return COMMON + FRAGMENTS[scene];
}

export function createShaderSceneEffect(scene: ShaderScene): ShaderSceneEffect {
  let renderer: THREE.WebGLRenderer | null = null;
  let threeScene: THREE.Scene | null = null;
  let camera: THREE.OrthographicCamera | null = null;
  let geometry: THREE.PlaneGeometry | null = null;
  let material: THREE.ShaderMaterial | null = null;

  function init(canvas: HTMLCanvasElement) {
    if (renderer) return;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false });
    renderer.setPixelRatio(
      typeof window !== "undefined" ? Math.min(window.devicePixelRatio || 1, 1.5) : 1,
    );
    const w = canvas.clientWidth || 1;
    const h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    threeScene = new THREE.Scene();
    camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    geometry = new THREE.PlaneGeometry(2, 2);
    material = new THREE.ShaderMaterial({
      vertexShader: VERTEX,
      fragmentShader: fragmentFor(scene),
      uniforms: {
        u_res: { value: new THREE.Vector2(w, h) },
        u_time: { value: 0 },
        u_beat: { value: 0 },
        u_kick: { value: 0 },
        u_accent: { value: 0 },
        u_bass: { value: 0 },
        u_mid: { value: 0 },
        u_high: { value: 0 },
        u_level: { value: 0 },
        u_colA: { value: new THREE.Vector3(0, 0.8, 1) },
        u_colB: { value: new THREE.Vector3(0.6, 0.4, 1) },
        u_sym: { value: 8 },
      },
    });
    threeScene.add(new THREE.Mesh(geometry, material));
  }

  function render(f: SceneFrame) {
    if (!renderer || !threeScene || !camera || !material) return;
    const u = material.uniforms;
    u.u_time.value = f.time;
    u.u_beat.value = f.beat;
    u.u_kick.value = f.kick;
    u.u_accent.value = f.accent;
    u.u_bass.value = f.bass;
    u.u_mid.value = f.mid;
    u.u_high.value = f.high;
    u.u_level.value = f.level;
    (u.u_colA.value as THREE.Vector3).set(f.colorA[0], f.colorA[1], f.colorA[2]);
    (u.u_colB.value as THREE.Vector3).set(f.colorB[0], f.colorB[1], f.colorB[2]);
    u.u_sym.value = f.symmetry;
    renderer.render(threeScene, camera);
  }

  function resize(width: number, height: number) {
    if (!renderer || !material) return;
    renderer.setSize(width, height, false);
    (material.uniforms.u_res.value as THREE.Vector2).set(width, height);
  }

  function destroy() {
    geometry?.dispose();
    material?.dispose();
    renderer?.dispose();
    geometry = null;
    material = null;
    renderer = null;
    threeScene = null;
    camera = null;
  }

  return { scene, init, render, resize, destroy };
}
