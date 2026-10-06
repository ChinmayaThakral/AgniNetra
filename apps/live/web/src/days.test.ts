import { describe, expect, it } from "vitest";
import { bestStreak, previousDay, streakOf } from "./days";

describe("days", () => {
  it("steps back across a month and a year", () => {
    expect(previousDay("2026-11-01")).toBe("2026-10-31");
    expect(previousDay("2027-01-01")).toBe("2026-12-31");
  });

  it("counts the run ending today, and stops at a gap", () => {
    const days = { "2026-10-18": 1, "2026-10-19": 1, "2026-10-20": 1, "2026-10-15": 1 };
    expect(streakOf(days, "2026-10-20")).toBe(3);
    expect(streakOf(days, "2026-10-21")).toBe(0);
  });

  it("finds the longest run anywhere", () => {
    expect(bestStreak({ "2026-10-01": 1, "2026-10-02": 1, "2026-10-05": 1, "2026-10-06": 1, "2026-10-07": 1 })).toBe(3);
    expect(bestStreak({})).toBe(0);
  });
});
