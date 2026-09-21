/**
 * The top bar shows ROOMS, not journeys (2026-09-21): Home · Catalog ·
 * Generations · Algorave · Settings. Create and Perform stay as routes —
 * the active-tab mapping and `/live`'s hidden nav still need their ids —
 * but they are reached from Home and from a session, not from a tab.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { NAV_ROUTES, ROUTES, Shell } from "@/components/ember/Shell";

vi.mock("next/navigation", () => ({ usePathname: () => "/catalog" }));

describe("the top bar", () => {
  it("offers the five rooms, in order, with Home first", () => {
    expect(NAV_ROUTES.map((r) => r.label)).toEqual(["Home", "Catalog", "Generations", "Algorave", "Settings"]);
  });

  it("keeps Create and Perform as routes but not as tabs", () => {
    const ids = ROUTES.map((r) => r.id);
    expect(ids).toContain("create");
    expect(ids).toContain("perform");
    render(<Shell username="pa"><div /></Shell>);
    const nav = screen.getByRole("navigation", { name: "Apollo product" });
    const labels = Array.from(nav.querySelectorAll("a")).map((a) => a.textContent);
    expect(labels).toEqual(["Home", "Catalog", "Generations", "Algorave", "Settings"]);
    expect(labels).not.toContain("Create");
    expect(labels).not.toContain("Perform");
    expect(labels).not.toContain("Library");
  });
});
