import { describe, expect, it } from "vitest";
import { SHOWCASE_BRIEFS, pickShowcaseBrief, showcaseById } from "@/lib/showcase";

describe("the showcase briefs", () => {
  it("each names its genre and a duration inside the sentence — that is what the parser reads", () => {
    for (const b of SHOWCASE_BRIEFS) {
      const text = b.brief.toLowerCase();
      expect(text).toMatch(/20-minute|twenty minutes/);
      // The genre folder's leading word must be in the sentence.
      expect(text).toContain(b.genre.split(" ")[0].toLowerCase());
    }
  });

  it("rotates deterministically and never falls off the list", () => {
    const seen = new Set<string>();
    for (let s = 0; s < SHOWCASE_BRIEFS.length * 3; s++) seen.add(pickShowcaseBrief(s).id);
    expect(seen.size).toBe(SHOWCASE_BRIEFS.length);
    expect(pickShowcaseBrief(-1).id).toBe(pickShowcaseBrief(1).id);
    expect(pickShowcaseBrief(7.9)).toBe(pickShowcaseBrief(7));
  });

  it("finds a brief by id, and says so when it cannot", () => {
    expect(showcaseById("rainy-lofi")?.genre).toBe("lofi - ambient");
    expect(showcaseById("nope")).toBeNull();
  });
});
