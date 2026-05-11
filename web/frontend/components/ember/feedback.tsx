"use client";
/**
 * Apollo v2.6.0 — Feedback primitives.
 *
 * Toast, Banner, Skeleton, Spinner. All passive (no overlay, no focus
 * trap) so any screen can drop one in without disrupting layout.
 *
 * Toasts are pushed via the module-level dispatch (`pushToast`) so
 * server-error paths can fire from any client component without
 * threading a context prop. The provider lives once in `app/layout.tsx`.
 */
import * as React from "react";
import { AnimatePresence, motion } from "motion/react";

function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

// ─── Toast ───────────────────────────────────────────────────────────────

export type ToastVariant = "info" | "ok" | "warn" | "error";

export type Toast = {
  id: string;
  variant: ToastVariant;
  message: string;
  /** Optional inline action — primary CTA on the right of the card. */
  action?: { label: string; onClick: () => void };
  /** ms before auto-dismiss. 0 disables auto-dismiss. Default 4000. */
  duration?: number;
};

type ToastInput = Omit<Toast, "id">;

type Listener = (toasts: Toast[]) => void;

const _toasts: Toast[] = [];
const _listeners = new Set<Listener>();

function _emit() {
  for (const l of _listeners) l([..._toasts]);
}

function _id() {
  return Math.random().toString(36).slice(2, 9);
}

/** Push a toast from anywhere (client component, error handler, hook). */
export function pushToast(input: ToastInput): string {
  const id = _id();
  const t: Toast = { id, ...input };
  _toasts.push(t);
  _emit();
  const ms = input.duration ?? 4000;
  if (ms > 0) {
    setTimeout(() => dismissToast(id), ms);
  }
  return id;
}

export function dismissToast(id: string): void {
  const idx = _toasts.findIndex((t) => t.id === id);
  if (idx === -1) return;
  _toasts.splice(idx, 1);
  _emit();
}

/** Convenience helpers — match common error-handler call sites. */
export const toast = {
  info: (message: string, opts?: Partial<ToastInput>) =>
    pushToast({ variant: "info", message, ...opts }),
  ok: (message: string, opts?: Partial<ToastInput>) =>
    pushToast({ variant: "ok", message, ...opts }),
  warn: (message: string, opts?: Partial<ToastInput>) =>
    pushToast({ variant: "warn", message, ...opts }),
  error: (message: string, opts?: Partial<ToastInput>) =>
    pushToast({ variant: "error", message, ...opts }),
};

const TOAST_VARIANT_CLS: Record<ToastVariant, string> = {
  info: "border-line2 text-ember-text",
  ok: "border-ok/40 text-ok",
  warn: "border-warn/40 text-warn",
  error: "border-ember/50 text-ember",
};

function ToastCard({ t }: { t: Toast }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 10, transition: { duration: 0.16 } }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className={cn(
        "pointer-events-auto flex items-start gap-3 border bg-surf",
        "px-4 py-3 max-w-[360px] shadow-lg",
        TOAST_VARIANT_CLS[t.variant],
      )}
      role={t.variant === "error" ? "alert" : "status"}
    >
      <div className="flex-1 font-sans text-[13px] leading-[1.4] text-ember-text">
        {t.message}
      </div>
      {t.action && (
        <button
          onClick={() => {
            t.action!.onClick();
            dismissToast(t.id);
          }}
          className="font-mono text-[10px] uppercase tracking-mono text-cream hover:brightness-110 cursor-pointer"
        >
          {t.action.label}
        </button>
      )}
      <button
        onClick={() => dismissToast(t.id)}
        aria-label="Dismiss"
        className="font-mono text-[10px] uppercase tracking-mono text-faint hover:text-ember-text cursor-pointer"
      >
        ✕
      </button>
    </motion.div>
  );
}

/** Drop once near the root of the app (e.g. in `app/layout.tsx`). */
export function ToastProvider() {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  React.useEffect(() => {
    _listeners.add(setToasts);
    setToasts([..._toasts]);
    return () => {
      _listeners.delete(setToasts);
    };
  }, []);
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-6 right-6 z-50 flex flex-col gap-2"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <ToastCard key={t.id} t={t} />
        ))}
      </AnimatePresence>
    </div>
  );
}

// ─── Banner ──────────────────────────────────────────────────────────────

export type BannerTone = "info" | "ok" | "warn" | "error";

export function Banner({
  tone = "info",
  className,
  children,
}: {
  tone?: BannerTone;
  className?: string;
  children: React.ReactNode;
}) {
  const toneCls: Record<BannerTone, string> = {
    info: "border-line2 text-mute",
    ok: "border-ok/40 text-ok",
    warn: "border-warn/40 text-warn",
    error: "border-ember/50 text-ember",
  };
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-center gap-3 border bg-surf/60 px-4 py-2",
        "font-mono text-[11px] uppercase tracking-mono",
        toneCls[tone],
        className,
      )}
    >
      {children}
    </div>
  );
}

// ─── Skeleton ────────────────────────────────────────────────────────────

/** Animated placeholder for async loads. Use `w-*` and `h-*` to size. */
export function Skeleton({
  className,
  rounded = false,
}: {
  className?: string;
  rounded?: boolean;
}) {
  return (
    <div
      aria-hidden
      className={cn(
        "relative overflow-hidden bg-surf2",
        rounded && "rounded-sm",
        className,
      )}
    >
      <div className="absolute inset-0 animate-pulse bg-line/40" />
    </div>
  );
}

// ─── Spinner ─────────────────────────────────────────────────────────────

/** 14px monotone rotating icon. Inherits `currentColor`. */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="14"
      height="14"
      className={cn("animate-spin", className)}
      aria-hidden
    >
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity="0.25" fill="none" strokeWidth="1.5" />
      <path d="M14 8a6 6 0 00-6-6" stroke="currentColor" fill="none" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
