import { describe, expect, it } from "vitest";
import { reconcile, sameValue } from "./progress-sync";

describe("progress reconciliation", () => {
  it("keeps server history alongside additions and same-key edits made during the request", () => {
    const sent = { heatle: { today: { solved: false, clue: 4 } }, visits: { yesterday: "Poor" } };
    const current = {
      heatle: { today: { solved: true, clue: 2 }, local: { solved: false, clue: 6 } },
      swipe: { s0123456789: { a: "unsure" as const, at: "2026-10-23T12:00:00Z" } },
      visits: { yesterday: "Moderate", today: null },
    };
    const reply = { heatle: { today: { solved: false, clue: 5 }, remote: { solved: true, clue: 1 } }, visits: { yesterday: "Severe", remote: "Good" } };
    const result = reconcile(sent, current, reply);
    expect(result.heatle).toEqual({ ...reply.heatle, ...current.heatle });
    expect(result.swipe).toEqual(current.swipe);
    expect(result.visits).toEqual({ yesterday: "Moderate", today: null, remote: "Good" });
  });

  it("accepts returned changes to entries that have not changed locally", () => {
    const sent = { heatle: { today: { solved: false, clue: 4 } }, city: "Delhi", theme: "light" as const };
    const reply = { heatle: { today: { solved: true, clue: 1 } }, city: "Patna", theme: "dark" as const };
    expect(reconcile(sent, structuredClone(sent), reply)).toMatchObject(reply);
  });

  it("preserves changed preferences and missing response history", () => {
    const sent = { city: "Delhi", theme: "light" as const, visits: { yesterday: "Poor" } };
    const current = { ...sent, city: "Patna", theme: "dark" as const };
    expect(reconcile(sent, current, { city: "Mumbai", theme: "light" })).toMatchObject(current);
  });

  it.each([[30, 12, 30], [12, 30, 30], [30, 30, 30]])("takes maximum XP, not summed XP (%i, %i)", (current, reply, expected) => {
    expect(reconcile({ pet: { xp: 5 } }, { pet: { xp: current } }, { pet: { xp: reply } }).pet?.xp).toBe(expected);
  });

  it("compares values without depending on property order or absent optional fields", () => {
    expect(sameValue({ pet: { xp: 3 }, visits: { a: null, b: "Good" } }, { visits: { b: "Good", a: null }, pet: { xp: 3 }, city: undefined })).toBe(true);
    expect(sameValue({ visits: { a: null } }, { visits: {} })).toBe(false);
    expect(sameValue({ heatle: { a: { solved: true, clue: 1 } } }, { heatle: { a: { solved: true, clue: 2 } } })).toBe(false);
  });
});
