/**
 * LiveLeaveGuard — a click on an in-app link while a set plays is held
 * behind a dialog instead of unmounting the engine (the 2026-09-23 loss).
 */
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import LiveLeaveGuard from "@/components/LiveLeaveGuard";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

afterEach(() => {
  push.mockReset();
  cleanup(); // unmount, so no earlier guard's document listener survives
});

function page(active: boolean) {
  const outside = vi.fn();
  render(
    <>
      <a href="/catalog" onClick={(e) => { outside(); e.preventDefault(); }}>
        Catalog
      </a>
      <LiveLeaveGuard active={active} trackName="Moon Tide" />
    </>,
  );
  return outside;
}

describe("LiveLeaveGuard", () => {
  it("holds an in-app link behind the dialog while live", async () => {
    const linkHandler = page(true);
    await act(async () => {
      fireEvent.click(screen.getByText("Catalog"));
    });
    expect(linkHandler).not.toHaveBeenCalled(); // next/link never saw it
    expect(screen.getByTestId("live-leave-guard")).toBeTruthy();
    expect(screen.getByText(/Moon Tide/)).toBeTruthy();
    expect(push).not.toHaveBeenCalled();
  });

  it("Keep playing closes the dialog and goes nowhere", async () => {
    page(true);
    await act(async () => {
      fireEvent.click(screen.getByText("Catalog"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("live-leave-stay"));
    });
    expect(push).not.toHaveBeenCalled();
  });

  it("Leave navigates to where the click was going", async () => {
    page(true);
    await act(async () => {
      fireEvent.click(screen.getByText("Catalog"));
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("live-leave-confirm"));
    });
    expect(push).toHaveBeenCalledWith("/catalog");
  });

  it("does nothing when no set is playing", async () => {
    const linkHandler = page(false);
    await act(async () => {
      fireEvent.click(screen.getByText("Catalog"));
    });
    expect(linkHandler).toHaveBeenCalled();
    expect(screen.queryByTestId("live-leave-guard")).toBeNull();
  });

  it("arms the browser's own prompt for reloads while live", () => {
    page(true);
    const ev = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(ev);
    expect(ev.defaultPrevented).toBe(true);
  });
});
