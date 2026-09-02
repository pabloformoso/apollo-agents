/**
 * Where the browser's WebSockets go.
 *
 * The bug being pinned: a hardcoded `ws://localhost:4020` in the CLIENT bundle
 * means "the machine with the tab open". Opened from anywhere but the server
 * itself, every socket dialled the viewer's own laptop and failed silently —
 * the HTTP half kept working (same-origin through the Next rewrite), so the
 * page just said "no brief yet" forever. The test that matters is therefore the
 * one where the page host is NOT localhost.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { wsBase } from "@/lib/ws-base";

function pageAt(href: string) {
  const u = new URL(href);
  vi.stubGlobal("window", {
    location: { protocol: u.protocol, hostname: u.hostname, host: u.host },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("wsBase", () => {
  it("follows the page host — the whole point", () => {
    pageAt("http://100.68.5.104:4010/live");
    expect(wsBase()).toBe("ws://100.68.5.104:4020");
    // Said explicitly, because this exact string was the bug:
    expect(wsBase()).not.toContain("localhost");
  });

  it("still works when the page IS localhost", () => {
    pageAt("http://localhost:4010/");
    expect(wsBase()).toBe("ws://localhost:4020");
  });

  it("uses wss: on an https page — ws: would be blocked as mixed content", () => {
    pageAt("https://apollo.example.com/live");
    expect(wsBase()).toBe("wss://apollo.example.com:4020");
  });

  it("keeps the page's host even on a non-default page port", () => {
    // The page port and the backend port are unrelated; only the HOST is
    // inherited. A dev server on 4011 still talks to the backend on 4020.
    pageAt("http://100.68.5.104:4011/");
    expect(wsBase()).toBe("ws://100.68.5.104:4020");
  });

  it("lets NEXT_PUBLIC_WS_BASE win — the E2E suite pins its mock with it", () => {
    vi.stubEnv("NEXT_PUBLIC_WS_BASE", "ws://localhost:8801");
    pageAt("http://100.68.5.104:4010/");
    expect(wsBase()).toBe("ws://localhost:8801");
  });

  it("derives from NEXT_PUBLIC_API_BASE when that is the one configured", () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE", "https://api.example.com");
    pageAt("http://100.68.5.104:4010/");
    expect(wsBase()).toBe("wss://api.example.com");
  });

  it("does not throw on the server, where there is no location", () => {
    vi.stubGlobal("window", undefined);
    expect(() => wsBase()).not.toThrow();
  });
});
