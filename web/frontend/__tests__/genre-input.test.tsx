import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import React from "react";
import GenreInput from "@/components/GenreInput";

// happy-dom doesn't auto-cleanup between tests.
afterEach(() => {
  cleanup();
});

describe("GenreInput — v2.5.0 environment perception", () => {
  it("renders both the genre input and the environment textarea", () => {
    render(<GenreInput onSubmit={() => {}} disabled={false} />);
    expect(
      screen.getByPlaceholderText(/60-minute cyberpunk set/i),
    ).toBeTruthy();
    expect(screen.getByLabelText(/Listening environment/i)).toBeTruthy();
  });

  it("submits the bare genre string when environment is empty", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    const genre = screen.getByPlaceholderText(/60-minute cyberpunk set/i);
    fireEvent.change(genre, { target: { value: "techno 30min" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSubmit).toHaveBeenCalledWith("techno 30min");
  });

  it("appends the environment textarea value as (environment: ...) when present", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    fireEvent.change(screen.getByPlaceholderText(/60-minute cyberpunk set/i), {
      target: { value: "techno 30min driving" },
    });
    fireEvent.change(screen.getByLabelText(/Listening environment/i), {
      target: { value: "loud crowded bar" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      "techno 30min driving (environment: loud crowded bar)",
    );
  });

  it("trims surrounding whitespace from both fields before composing", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    fireEvent.change(screen.getByPlaceholderText(/60-minute cyberpunk set/i), {
      target: { value: "  techno 30min  " },
    });
    fireEvent.change(screen.getByLabelText(/Listening environment/i), {
      target: { value: "  intimate listening  " },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      "techno 30min (environment: intimate listening)",
    );
  });

  it("does not submit when the genre input is empty (button disabled)", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    fireEvent.change(screen.getByLabelText(/Listening environment/i), {
      target: { value: "outdoor cafe" },
    });
    const button = screen.getByRole("button", { name: /send/i });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(button);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables both inputs and the button when disabled=true", () => {
    render(<GenreInput onSubmit={() => {}} disabled={true} />);
    const genre = screen.getByPlaceholderText(
      /60-minute cyberpunk set/i,
    ) as HTMLInputElement;
    const env = screen.getByLabelText(
      /Listening environment/i,
    ) as HTMLTextAreaElement;
    expect(genre.disabled).toBe(true);
    expect(env.disabled).toBe(true);
    expect(
      (screen.getByRole("button", { name: /send/i }) as HTMLButtonElement).disabled,
    ).toBe(true);
  });

  it("clears both fields after a successful submit", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    const genre = screen.getByPlaceholderText(
      /60-minute cyberpunk set/i,
    ) as HTMLInputElement;
    const env = screen.getByLabelText(
      /Listening environment/i,
    ) as HTMLTextAreaElement;
    fireEvent.change(genre, { target: { value: "techno 30min" } });
    fireEvent.change(env, { target: { value: "loud bar" } });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
    expect(genre.value).toBe("");
    expect(env.value).toBe("");
  });

  it("Enter on the genre input submits with the composed message", () => {
    const onSubmit = vi.fn();
    render(<GenreInput onSubmit={onSubmit} disabled={false} />);
    fireEvent.change(screen.getByPlaceholderText(/60-minute cyberpunk set/i), {
      target: { value: "techno" },
    });
    fireEvent.change(screen.getByLabelText(/Listening environment/i), {
      target: { value: "club" },
    });
    fireEvent.keyDown(screen.getByPlaceholderText(/60-minute cyberpunk set/i), {
      key: "Enter",
    });
    expect(onSubmit).toHaveBeenCalledWith("techno (environment: club)");
  });
});
