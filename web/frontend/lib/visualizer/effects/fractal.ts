/**
 * fractal — animated Julia-set effect rendered to a fullscreen quad.
 *
 * Uses a tiny fragment shader (~30 lines GLSL) that samples the Julia set
 * at a beat-driven ``c`` constant.  ``phase_in_beat`` modulates the
 * complex offset, BPM modulates the zoom, and the Camelot-key palette
 * sets the base hue.  Cheap to render — single full-viewport quad,
 * fixed iteration cap.
 *
 * Why Julia and not Mandelbrot: Julia's ``c`` constant gives us a
 * single-vector knob to drive with the beat.  Animating Mandelbrot
 * would require zooming/panning into specific basins which is harder
 * to keep visually pleasant across arbitrary BPMs.
 */
import * as THREE from "three";

import type { BeatClockResult } from "../beat_clock";
import { camelotToColor, hslToHex } from "../palette";

export interface FractalCurrentTrackInfo {
  bpm?: number | null;
  camelot_key?: string | null;
}

export interface FractalEffect {
  init(canvas: HTMLCanvasElement): void;
  render(beat: BeatClockResult, currentTrack: FractalCurrentTrackInfo | null): void;
  resize(width: number, height: number): void;
  destroy(): void;
}

const VERTEX_SHADER = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position, 1.0);
  }
`;

const FRAGMENT_SHADER = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform vec2 u_resolution;
  uniform vec2 u_c;          // Julia constant — beat-driven
  uniform float u_zoom;      // BPM-driven
  uniform float u_twist;     // small rotation per frame
  uniform vec3 u_color;      // base hue (RGB)

  vec2 cmul(vec2 a, vec2 b) {
    return vec2(a.x * b.x - a.y * b.y, a.x * b.y + a.y * b.x);
  }

  void main() {
    float aspect = u_resolution.x / max(1.0, u_resolution.y);
    vec2 uv = (vUv - 0.5) * 2.0;
    uv.x *= aspect;
    uv *= u_zoom;
    // Twist
    float ct = cos(u_twist);
    float st = sin(u_twist);
    uv = vec2(uv.x * ct - uv.y * st, uv.x * st + uv.y * ct);

    vec2 z = uv;
    int iter = 0;
    const int MAX_ITER = 64;
    for (int i = 0; i < MAX_ITER; i++) {
      z = cmul(z, z) + u_c;
      if (dot(z, z) > 4.0) {
        iter = i;
        break;
      }
      iter = i;
    }

    float t = float(iter) / float(MAX_ITER);
    vec3 col = u_color * (0.4 + 0.6 * t) + vec3(0.05) * (1.0 - t);
    gl_FragColor = vec4(col, 1.0);
  }
`;

export function createFractalEffect(): FractalEffect {
  let renderer: THREE.WebGLRenderer | null = null;
  let scene: THREE.Scene | null = null;
  let camera: THREE.OrthographicCamera | null = null;
  let mesh: THREE.Mesh | null = null;
  let material: THREE.ShaderMaterial | null = null;
  let geometry: THREE.PlaneGeometry | null = null;

  function init(canvas: HTMLCanvasElement) {
    if (renderer) return;
    renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false });
    renderer.setPixelRatio(
      typeof window !== "undefined" ? Math.min(window.devicePixelRatio, 2) : 1,
    );
    renderer.setSize(canvas.clientWidth || 1, canvas.clientHeight || 1, false);

    scene = new THREE.Scene();
    camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    geometry = new THREE.PlaneGeometry(2, 2);
    material = new THREE.ShaderMaterial({
      vertexShader: VERTEX_SHADER,
      fragmentShader: FRAGMENT_SHADER,
      uniforms: {
        u_resolution: {
          value: new THREE.Vector2(canvas.clientWidth || 1, canvas.clientHeight || 1),
        },
        u_c: { value: new THREE.Vector2(-0.7, 0.27015) },
        u_zoom: { value: 1.5 },
        u_twist: { value: 0 },
        u_color: { value: new THREE.Vector3(0.0, 0.9, 1.0) },
      },
    });
    mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
  }

  function render(beat: BeatClockResult, currentTrack: FractalCurrentTrackInfo | null) {
    if (!renderer || !scene || !camera || !material) return;

    const bpm = currentTrack?.bpm && currentTrack.bpm > 0 ? currentTrack.bpm : 120;
    const phase = beat.phase_in_beat;

    // c traces a slow circle; phase nudges it so each beat shifts the basin.
    const angle = beat.beat_index * 0.05 + phase * 0.5;
    const r = 0.7885;
    const cx = Math.cos(angle) * r * 0.9 - 0.05;
    const cy = Math.sin(angle * 1.3) * r * 0.6;
    (material.uniforms.u_c.value as THREE.Vector2).set(cx, cy);

    // Zoom pulses with each beat — cheaper to compute than a smooth lerp,
    // and the visual punch is more interesting.  Faster BPM → tighter
    // breathing range so the effect doesn't look frantic.
    const breathe = 1 - 0.15 * Math.pow(1 - phase, 2);
    const baseZoom = 1.5 - Math.min(0.4, bpm / 600);
    material.uniforms.u_zoom.value = baseZoom * breathe;

    // Twist drifts continuously; beat index gives it persistence between rAFs.
    material.uniforms.u_twist.value = beat.beat_index * 0.03 + phase * 0.05;

    const baseHsl = camelotToColor(currentTrack?.camelot_key);
    const hex = hslToHex(baseHsl);
    const r8 = ((hex >> 16) & 0xff) / 255;
    const g8 = ((hex >> 8) & 0xff) / 255;
    const b8 = (hex & 0xff) / 255;
    (material.uniforms.u_color.value as THREE.Vector3).set(r8, g8, b8);

    renderer.render(scene, camera);
  }

  function resize(width: number, height: number) {
    if (!renderer || !material) return;
    renderer.setSize(width, height, false);
    (material.uniforms.u_resolution.value as THREE.Vector2).set(width, height);
  }

  function destroy() {
    if (geometry) geometry.dispose();
    if (material) material.dispose();
    if (renderer) renderer.dispose();
    geometry = null;
    material = null;
    mesh = null;
    scene = null;
    camera = null;
    renderer = null;
  }

  return { init, render, resize, destroy };
}
