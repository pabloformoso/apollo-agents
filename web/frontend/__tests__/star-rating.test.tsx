import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import StarRating from "@/components/StarRating";

// happy-dom doesn't auto-cleanup between tests, so the previous render's
// nodes remain in document.body and break getByTestId (multiple matches).
afterEach(() => {
  cleanup();
});

describe("StarRating", () => {
  it("renders 5 stars; with value=3 the first 3 are filled", () => {
    render(
      <StarRating value={3} onChange={() => {}} onClear={() => {}} />,
    );
    const stars = screen.getAllByRole("radio");
    expect(stars).toHaveLength(5);
    // Filled state is exposed via data-filled, with the first N stars filled.
    expect(stars[0].getAttribute("data-filled")).toBe("true");
    expect(stars[1].getAttribute("data-filled")).toBe("true");
    expect(stars[2].getAttribute("data-filled")).toBe("true");
    expect(stars[3].getAttribute("data-filled")).toBe("false");
    expect(stars[4].getAttribute("data-filled")).toBe("false");
    // Glyph follows the same boundary.
    expect(stars[0].textContent).toBe("★");
    expect(stars[3].textContent).toBe("☆");
  });

  it("with value=null no star is filled", () => {
    render(
      <StarRating value={null} onChange={() => {}} onClear={() => {}} />,
    );
    const stars = screen.getAllByRole("radio");
    for (const s of stars) {
      expect(s.getAttribute("data-filled")).toBe("false");
      expect(s.textContent).toBe("☆");
    }
  });

  it("clicking star 4 fires onChange(4)", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <StarRating value={3} onChange={onChange} onClear={onClear} />,
    );
    fireEvent.click(screen.getByTestId("star-4"));
    expect(onChange).toHaveBeenCalledWith(4);
    expect(onClear).not.toHaveBeenCalled();
  });

  it("clicking the currently-selected star fires onClear", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <StarRating value={3} onChange={onChange} onClear={onClear} />,
    );
    fireEvent.click(screen.getByTestId("star-3"));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("with value=null, clicking star N fires onChange(N)", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <StarRating value={null} onChange={onChange} onClear={onClear} />,
    );
    fireEvent.click(screen.getByTestId("star-5"));
    expect(onChange).toHaveBeenCalledWith(5);
    fireEvent.click(screen.getByTestId("star-1"));
    expect(onChange).toHaveBeenCalledWith(1);
    expect(onClear).not.toHaveBeenCalled();
  });

  it("clicking does not bubble up to a parent click handler", () => {
    const parentClick = vi.fn();
    const onChange = vi.fn();
    render(
      <div onClick={parentClick}>
        <StarRating value={null} onChange={onChange} onClear={() => {}} />
      </div>,
    );
    fireEvent.click(screen.getByTestId("star-2"));
    expect(onChange).toHaveBeenCalledWith(2);
    // The whole point of the stop-propagation in the component is that the
    // wrapping clickable card / drawer doesn't see the click.
    expect(parentClick).not.toHaveBeenCalled();
  });

  it("Enter / Space on a filled star clears the rating", () => {
    const onChange = vi.fn();
    const onClear = vi.fn();
    render(
      <StarRating value={2} onChange={onChange} onClear={onClear} />,
    );
    fireEvent.keyDown(screen.getByTestId("star-2"), { key: "Enter" });
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });
});
