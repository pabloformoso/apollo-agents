"use client";
/**
 * Apollo v2.6.0 — Cinematic / Ember primitives.
 *
 * Direct port of the prototype components in
 * docs/design/apollo-claude-design/apollo/project/prototype-screens.jsx
 * and prototype-shell.jsx. Inline styles with PT.* tokens become Tailwind
 * classes on `ember.*` colours plus a thin `cn()` helper.
 *
 * Public exports
 * --------------
 * Crumb       Small monospaced uppercase label ("01 · brief", "now playing").
 * Btn         Button with four variants (primary | cream | ghost | quiet).
 * ApolloMark  The wordmark logo, italic serif with optional ember dot.
 * Stripe      Diagonal stripe placeholder for missing cover art.
 * Particles   Decorative SVG particles for the Live screen.
 * Arrow / Plus / Mic     14px stroked icons used by Btn children.
 */
import * as React from "react";

// Tiny class-merge helper — avoids pulling clsx for one use case.
function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ── Crumb ─────────────────────────────────────────────────────────────────
export function Crumb({
  children,
  className,
  tone = "faint",
}: {
  children: React.ReactNode;
  className?: string;
  tone?: "faint" | "ember" | "cream" | "mute";
}) {
  const toneCls =
    tone === "ember" ? "text-ember"
    : tone === "cream" ? "text-cream"
    : tone === "mute" ? "text-mute"
    : "text-faint";
  return (
    <span
      className={cn(
        "font-mono text-[10px] uppercase tracking-mono",
        toneCls,
        className,
      )}
    >
      {children}
    </span>
  );
}

// ── Btn ───────────────────────────────────────────────────────────────────
type BtnKind = "primary" | "cream" | "ghost" | "quiet";

export type BtnProps = {
  kind?: BtnKind;
  className?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

export function Btn({
  kind = "primary",
  className,
  children,
  disabled,
  ...rest
}: BtnProps) {
  const variant: Record<BtnKind, string> = {
    primary: "bg-ember text-cream border-none",
    cream: "bg-cream text-ink border-none",
    ghost: "bg-transparent text-ember-text border border-line2",
    quiet: "bg-transparent text-faint border-none",
  };
  return (
    <button
      {...rest}
      disabled={disabled}
      className={cn(
        // Layout — match the prototype's 12px/22px padding + gap-2.5 between icon and text.
        "inline-flex items-center gap-2.5 px-[22px] py-3",
        // Type — DM Sans 14px medium.
        "font-sans text-sm font-medium",
        // Cursor + a11y disabled state.
        "cursor-pointer transition-transform duration-[80ms] ease-out",
        "disabled:cursor-not-allowed disabled:opacity-50",
        // Subtle hover on solid buttons (matches the prototype's filter hover).
        "hover:brightness-110",
        variant[kind],
        className,
      )}
    >
      {children}
    </button>
  );
}

// ── ApolloMark ────────────────────────────────────────────────────────────
export function ApolloMark({
  size = 28,
  dot = true,
  className,
}: {
  size?: number;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "font-display italic tracking-[-0.022em] leading-none",
        "inline-flex items-baseline text-ember-text",
        className,
      )}
      style={{ fontSize: size }}
    >
      Apollo
      {dot && <span className="text-ember">.</span>}
    </span>
  );
}

// ── Stripe ────────────────────────────────────────────────────────────────
// Diagonal SVG placeholder used as cover-art empty state. The opacity tunes
// the visual prominence; surfaces with multiple stripe cards typically vary
// alpha by index for subtle differentiation.
export function Stripe({
  alpha = 0.18,
  className,
  rgb = "232,85,58",
  children,
}: {
  alpha?: number;
  className?: string;
  rgb?: string; // r,g,b
  children?: React.ReactNode;
}) {
  const svg = encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='8' height='8'><path d='M-1,1 l2,-2 M0,8 l8,-8 M7,9 l2,-2' stroke='rgba(${rgb},${alpha})' stroke-width='1'/></svg>`,
  );
  return (
    <div
      className={cn("border border-line", className)}
      style={{
        backgroundColor: "var(--surf)",
        backgroundImage: `url("data:image/svg+xml;utf8,${svg}")`,
      }}
    >
      {children}
    </div>
  );
}

// ── Particles ─────────────────────────────────────────────────────────────
// Decorative SVG particles laid over the Live audience / immersive screens.
// Static positions so the visualizer (which animates) draws over a calm
// backdrop instead of competing.
export function Particles({ count = 60 }: { count?: number }) {
  const dots = React.useMemo(
    () =>
      Array.from({ length: count }).map(() => ({
        x: Math.random() * 100,
        y: Math.random() * 100,
        r: Math.random() * 2.5,
        o: Math.random() * 0.7,
      })),
    [count],
  );
  return (
    <svg
      className="absolute inset-0 h-full w-full"
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      {dots.map((d, k) => (
        <circle
          key={k}
          cx={d.x}
          cy={d.y}
          r={d.r * 0.4}
          fill="var(--cream)"
          opacity={d.o}
        />
      ))}
    </svg>
  );
}

// ── Icons ─────────────────────────────────────────────────────────────────
const iconBase =
  "stroke-current fill-none";

export function Arrow({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      strokeWidth="1.5"
      className={cn(iconBase, className)}
      aria-hidden
    >
      <path d="M3 8h10M9 4l4 4-4 4" />
    </svg>
  );
}

export function Plus({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      strokeWidth="1.5"
      className={cn(iconBase, className)}
      aria-hidden
    >
      <path d="M8 3v10M3 8h10" />
    </svg>
  );
}

export function Mic({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      strokeWidth="1.4"
      className={cn(iconBase, className)}
      aria-hidden
    >
      <rect x="6" y="2" width="4" height="8" rx="2" />
      <path d="M3.5 8.5a4.5 4.5 0 009 0M8 13v2" />
    </svg>
  );
}
