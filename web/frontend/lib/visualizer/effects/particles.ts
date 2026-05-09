/**
 * particles — Three.js particle field, beat-reactive.
 *
 * A ``THREE.Points`` cloud where each particle drifts on a slow noise field.
 * On every beat the material's size + opacity pulse via a sin curve over
 * ``phase_in_beat``.  Every 16 beats the color hue rotates around the
 * Camelot palette so the field stays visually fresh through long sets.
 *
 * Performance notes
 * -----------------
 * - Particle count target: ~1500 — comfortably 60 fps on a 2020-era integrated
 *   GPU, well under any GPU's draw-call budget for a single Points buffer.
 * - All buffers live on the GPU; per-frame work is one uniform update +
 *   one transform of an attribute that we leave alone (drift comes from
 *   advancing positions in a typed array — N=1500 is cheap on the CPU
 *   side too).
 * - ``destroy()`` releases the geometry, material, renderer DOM canvas,
 *   and attaches no listeners.  The component above us is responsible
 *   for clearing the canvas reference.
 */
import * as THREE from "three";

import type { BeatClockResult } from "../beat_clock";
import { camelotToColor, hslToHex } from "../palette";

export interface CurrentTrackInfo {
  camelot_key?: string | null;
}

export interface ParticlesEffect {
  /** Bind the effect to a canvas. Idempotent. */
  init(canvas: HTMLCanvasElement): void;
  /** Per-frame render. Call from rAF loop after ``init``. */
  render(beat: BeatClockResult, currentTrack: CurrentTrackInfo | null): void;
  /** Resize handler — call when the canvas size changes. */
  resize(width: number, height: number): void;
  /** Free WebGL resources and detach. */
  destroy(): void;
}

const PARTICLE_COUNT = 1500;
const FIELD_RADIUS = 8;
const COLOR_SHIFT_INTERVAL_BEATS = 16;

export function createParticlesEffect(): ParticlesEffect {
  let renderer: THREE.WebGLRenderer | null = null;
  let scene: THREE.Scene | null = null;
  let camera: THREE.PerspectiveCamera | null = null;
  let geometry: THREE.BufferGeometry | null = null;
  let material: THREE.PointsMaterial | null = null;
  let points: THREE.Points | null = null;

  // Drift velocities — populated on init, mutated per-frame.
  const velocities = new Float32Array(PARTICLE_COUNT * 3);
  let positions: Float32Array | null = null;

  function init(canvas: HTMLCanvasElement) {
    if (renderer) return; // idempotent
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: true,
      powerPreference: "high-performance",
    });
    renderer.setPixelRatio(
      typeof window !== "undefined" ? Math.min(window.devicePixelRatio, 2) : 1,
    );
    renderer.setSize(canvas.clientWidth || 1, canvas.clientHeight || 1, false);
    renderer.setClearColor(0x000000, 0);

    scene = new THREE.Scene();
    camera = new THREE.PerspectiveCamera(
      60,
      (canvas.clientWidth || 1) / (canvas.clientHeight || 1),
      0.1,
      100,
    );
    camera.position.z = FIELD_RADIUS;

    geometry = new THREE.BufferGeometry();
    positions = new Float32Array(PARTICLE_COUNT * 3);
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      // Spherical distribution.
      const r = Math.random() * FIELD_RADIUS;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i3] = r * Math.sin(phi) * Math.cos(theta);
      positions[i3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      positions[i3 + 2] = r * Math.cos(phi);
      // Tiny drift velocity.
      velocities[i3] = (Math.random() - 0.5) * 0.002;
      velocities[i3 + 1] = (Math.random() - 0.5) * 0.002;
      velocities[i3 + 2] = (Math.random() - 0.5) * 0.002;
    }
    geometry.setAttribute(
      "position",
      new THREE.BufferAttribute(positions, 3),
    );

    material = new THREE.PointsMaterial({
      size: 0.05,
      color: 0x00e5ff,
      transparent: true,
      opacity: 0.85,
      sizeAttenuation: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    points = new THREE.Points(geometry, material);
    scene.add(points);
  }

  function render(beat: BeatClockResult, currentTrack: CurrentTrackInfo | null) {
    if (!renderer || !scene || !camera || !material || !geometry || !positions) {
      return;
    }
    // Drift particles + bounce off the radius shell.
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      positions[i3] += velocities[i3];
      positions[i3 + 1] += velocities[i3 + 1];
      positions[i3 + 2] += velocities[i3 + 2];
      const x = positions[i3];
      const y = positions[i3 + 1];
      const z = positions[i3 + 2];
      const dist2 = x * x + y * y + z * z;
      if (dist2 > FIELD_RADIUS * FIELD_RADIUS) {
        velocities[i3] *= -1;
        velocities[i3 + 1] *= -1;
        velocities[i3 + 2] *= -1;
      }
    }
    const posAttr = geometry.getAttribute("position") as THREE.BufferAttribute;
    posAttr.needsUpdate = true;

    // Beat-reactive size + opacity. We model each beat as a fast-rise /
    // slow-decay envelope so the pulse feels musical rather than uniform.
    const phase = beat.phase_in_beat;
    const envelope = Math.pow(1 - phase, 2); // 1 at start of beat, 0 at end
    const baseSize = 0.05;
    material.size = baseSize + envelope * 0.06;
    material.opacity = 0.55 + envelope * 0.4;

    // Color shift every 16 beats — interpolate the Camelot palette around
    // the wheel by adding a beat-driven hue offset.
    const baseHsl = camelotToColor(currentTrack?.camelot_key);
    const cycle = beat.beat_index / COLOR_SHIFT_INTERVAL_BEATS;
    const hueOffset = (cycle * 30) % 360; // 30° per 16 beats
    const hex = hslToHex({
      h: baseHsl.h + hueOffset,
      s: baseHsl.s,
      l: baseHsl.l,
    });
    material.color.setHex(hex);

    // Slow rotation so the field has motion even between beats.
    if (points) {
      points.rotation.y += 0.0015;
      points.rotation.x += 0.0007;
    }

    renderer.render(scene, camera);
  }

  function resize(width: number, height: number) {
    if (!renderer || !camera) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / Math.max(1, height);
    camera.updateProjectionMatrix();
  }

  function destroy() {
    if (geometry) geometry.dispose();
    if (material) material.dispose();
    if (renderer) {
      renderer.dispose();
      // Don't remove the canvas from the DOM — the component owns it.
    }
    geometry = null;
    material = null;
    scene = null;
    camera = null;
    points = null;
    renderer = null;
    positions = null;
  }

  return { init, render, resize, destroy };
}
