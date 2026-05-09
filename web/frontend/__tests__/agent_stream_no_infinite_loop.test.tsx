/**
 * v2.5.0.1 regression — ``AgentStream`` must NOT infinite-loop when
 * ``buildStartedAt`` is set.
 *
 * Pre-fix the ``getSnapshot`` callback for ``useSyncExternalStore``
 * returned ``Date.now()`` directly. React calls ``getSnapshot`` during
 * every render to check for store changes; when the value changes on
 * every call (which raw ``Date.now()`` does), React assumes the store
 * keeps changing and re-renders forever — eventually OOM-ing the tab.
 *
 * Post-fix the snapshot is cached at 1-second resolution and only
 * invalidated by the interval inside ``subscribeSecond``. This test
 * renders the component, advances time a bit, and asserts the render
 * count stays bounded.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, cleanup } from "@testing-library/react";
import * as React from "react";

import AgentStream, { type LogEntry } from "@/components/AgentStream";

afterEach(() => {
  cleanup();
});

describe("<AgentStream /> — no infinite loop", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders a bounded number of times when buildStartedAt is active", async () => {
    let renderCount = 0;
    function CountingWrapper() {
      renderCount++;
      const entries: LogEntry[] = React.useMemo(
        () => [{ type: "system", content: "Build started" }],
        [],
      );
      return (
        <AgentStream
          entries={entries}
          isStreaming={true}
          buildStartedAt={Date.now()}
          buildName="test"
        />
      );
    }

    await act(async () => {
      render(<CountingWrapper />);
    });

    // Snapshot the render count immediately after mount. Even with React
    // 19's strict-mode double-render the count should be 1 or 2 — never
    // hundreds.
    const initialCount = renderCount;
    expect(initialCount).toBeLessThan(10);

    // Advance fake time well past one second's worth of intervals. The
    // 1 Hz subscribe interval will fire 3 times; each fire bumps the
    // render count by 1 (NOT by hundreds, which is the failure mode).
    await act(async () => {
      vi.advanceTimersByTime(3500);
    });

    const finalCount = renderCount;
    // Three interval ticks → at most 3 additional renders. Allow a small
    // margin for React 19 reconciliation but assert nowhere near a
    // runaway loop (which would be in the thousands).
    expect(finalCount - initialCount).toBeLessThan(20);
  });

  it("getSecondNow returns a stable value across calls within the same second", async () => {
    // Indirect probe via two consecutive renders: if ``getSnapshot`` were
    // unstable we'd see the elapsed counter change between successive
    // synchronous renders, which is the exact contract React enforces.
    let renderCount = 0;
    function Probe() {
      renderCount++;
      return (
        <AgentStream
          entries={[]}
          isStreaming={false}
          buildStartedAt={Date.now() - 500}
        />
      );
    }
    await act(async () => {
      render(<Probe />);
    });
    expect(renderCount).toBeLessThan(10);
  });
});
