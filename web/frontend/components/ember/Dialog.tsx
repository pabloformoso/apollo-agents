"use client";
/**
 * Apollo v2.6.0 — Dialog primitive.
 *
 * Minimal modal with backdrop blur + Esc-to-close + click-outside-to-close.
 * Renders into a portal at `document.body` so it sits above the Shell
 * (including the Live route's broadcasting overlay).
 *
 * No focus trap — autoFocus the first input/button you care about. This
 * keeps the primitive dependency-free; if accessibility audits later
 * demand a trap, plug @radix-ui/react-focus-scope in here.
 */
import * as React from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";

function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export type DialogProps = {
  open: boolean;
  onClose: () => void;
  /** Optional aria-label so screen readers announce the dialog's purpose. */
  label?: string;
  /** Width preset. `default` = 480px, `wide` = 720px, `full` = 90vw. */
  width?: "default" | "wide" | "full";
  /** Render-prop content; you control the surface layout. */
  children: React.ReactNode;
  /** Tailwind class override applied to the surface (the inner box). */
  surfaceClassName?: string;
};

const WIDTH_CLS = {
  default: "w-[min(480px,calc(100vw-32px))]",
  wide: "w-[min(720px,calc(100vw-32px))]",
  full: "w-[90vw] h-[90vh]",
};

export function Dialog({
  open,
  onClose,
  label,
  width = "default",
  children,
  surfaceClassName,
}: DialogProps) {
  // SSR safety — `document` does not exist until mount. Render nothing on
  // the server; the first client paint kicks in immediately after.
  const [mounted, setMounted] = React.useState(false);
  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Lock body scroll while open so the modal isn't fighting the page.
  React.useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!mounted) return null;

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="dialog"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-ink/70 backdrop-blur-sm"
          onClick={onClose}
          role="dialog"
          aria-modal="true"
          aria-label={label}
        >
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.22, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
            className={cn(
              "relative border border-line2 bg-surf",
              WIDTH_CLS[width],
              "max-h-[85vh] overflow-auto",
              surfaceClassName,
            )}
          >
            {children}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
