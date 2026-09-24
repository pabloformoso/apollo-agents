/** leavingTo — which clicks on a live page need a "stop the set?" confirm. */
import { describe, expect, it } from "vitest";

import { leavingTo } from "@/lib/leave_guard";

const HERE = "http://jarvis:4010/live?session=abc#booth";
const click = (href: string, extra: Partial<Parameters<typeof leavingTo>[0]> = {}) =>
  leavingTo({ href, button: 0, ...extra }, HERE);

describe("leavingTo", () => {
  it("catches an in-app link to another page (the lost-set click)", () => {
    expect(click("http://jarvis:4010/catalog")).toBe("/catalog");
    expect(click("/dashboard?tab=2")).toBe("/dashboard?tab=2");
  });

  it("lets through clicks that keep this tab on the page", () => {
    expect(click("#immersive")).toBeNull();
    expect(click("http://jarvis:4010/live?session=abc#cabin")).toBeNull();
  });

  it("treats a different session on the same route as leaving", () => {
    expect(click("/live?session=other")).toBe("/live?session=other");
  });

  it("ignores new-tab, modified, middle and download clicks", () => {
    expect(click("/catalog", { target: "_blank" })).toBeNull();
    expect(click("/catalog", { metaKey: true })).toBeNull();
    expect(click("/catalog", { ctrlKey: true })).toBeNull();
    expect(click("/catalog", { shiftKey: true })).toBeNull();
    expect(click("/catalog", { button: 1 })).toBeNull();
    expect(click("/api/export.zip", { download: true })).toBeNull();
    expect(click("/catalog", { target: "_self" })).toBe("/catalog");
  });

  it("ignores other origins (beforeunload covers those)", () => {
    expect(click("https://youtube.com/live")).toBeNull();
  });

  it("never throws on a malformed href", () => {
    expect(leavingTo({ href: "http://[bad", button: 0 }, HERE)).toBeNull();
  });
});
