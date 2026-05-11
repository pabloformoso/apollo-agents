"use client";
/**
 * Apollo v2.6.0 — Motion helpers.
 *
 * Thin wrappers around `motion` v12 (Framer Motion) so the screens stay
 * declarative and the timing constants live in one place. The variants
 * are deliberately conservative — the design language relies on
 * typography and colour for its impact; motion is supportive, not the
 * star.
 */
import { AnimatePresence, motion, type Variants } from "motion/react";

export { AnimatePresence, motion };

/** Page-level enter: subtle fade + 6px lift. ~280 ms. */
export const pageVariants: Variants = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.28, ease: "easeOut" } },
  exit: { opacity: 0, y: -4, transition: { duration: 0.16, ease: "easeIn" } },
};

/** Stagger children by 60 ms — used in section reveals (e.g. Brief
 * suggestion list, parsed-fields grid). */
export const listVariants: Variants = {
  initial: {},
  animate: { transition: { staggerChildren: 0.06, delayChildren: 0.04 } },
};

/** Single list-item enter: tiny rise + fade. */
export const itemVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0, transition: { duration: 0.22, ease: "easeOut" } },
};

/** Cross-fade for the Live mode switcher — 200 ms in, 120 ms out. */
export const modeVariants: Variants = {
  initial: { opacity: 0 },
  animate: { opacity: 1, transition: { duration: 0.20, ease: "easeOut" } },
  exit: { opacity: 0, transition: { duration: 0.12, ease: "easeIn" } },
};

/** Tap micro-interaction — small scale-down on press. */
export const tap = { scale: 0.97 };
