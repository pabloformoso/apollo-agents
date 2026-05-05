"use client";
import React from "react";

/**
 * Reusable, controlled 5-star rating widget. Clicking a non-selected star N
 * fires onChange(N); clicking a star already selected (value === N) fires
 * onClear so the user can reset their rating with a single click.
 *
 * Visual style — Unicode ★ / ☆ to match the project's font-pixel/cyberpunk
 * aesthetic, with `text-neon` for filled and `text-muted` for empty.
 */
export type StarSize = "sm" | "md";

export interface StarRatingProps {
  value: number | null;
  onChange: (rating: number) => void;
  onClear: () => void;
  size?: StarSize;
  /** Optional aria label for the wrapping group (e.g. track title). */
  label?: string;
  /** Optional className passthrough so callers can position the widget. */
  className?: string;
}

const SIZE_CLASS: Record<StarSize, string> = {
  sm: "text-sm leading-none",
  md: "text-2xl leading-none",
};

export default function StarRating({
  value,
  onChange,
  onClear,
  size = "sm",
  label,
  className,
}: StarRatingProps) {
  const filled = value ?? 0;

  const handleClick = (n: number, e: React.MouseEvent) => {
    // Prevent propagation so a star inside a clickable card / drawer link
    // doesn't double-trigger (e.g. opening the detail panel).
    e.stopPropagation();
    if (filled === n) {
      onClear();
    } else {
      onChange(n);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={label ? `Rating for ${label}` : "Rating"}
      data-testid="star-rating"
      className={[
        "inline-flex items-center gap-0.5",
        SIZE_CLASS[size],
        className ?? "",
      ].join(" ")}
    >
      {[1, 2, 3, 4, 5].map((n) => {
        const isFilled = n <= filled;
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={value === n}
            aria-label={`${n} star${n === 1 ? "" : "s"}`}
            data-testid={`star-${n}`}
            data-filled={isFilled ? "true" : "false"}
            onClick={(e) => handleClick(n, e)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                if (filled === n) onClear();
                else onChange(n);
              }
            }}
            className={[
              "select-none transition-colors px-0.5",
              isFilled
                ? "text-neon hover:text-neon-dim"
                : "text-muted hover:text-neon",
              "focus:outline-none focus:text-neon",
            ].join(" ")}
          >
            {isFilled ? "★" : "☆"}
          </button>
        );
      })}
    </div>
  );
}
