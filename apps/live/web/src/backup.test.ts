import { describe, expect, it } from "vitest";
import { Backup, merge } from "./backup";

describe("backup", () => {
  it("keeps both histories and the larger experience", () => {
    const merged = merge(
      { pet: { xp: 30 }, heatle: { "2026-10-01": { solved: true, clue: 2 } }, city: "Delhi" },
      { pet: { xp: 12 }, heatle: { "2026-10-02": { solved: false, clue: 6 } }, city: "Patna" },
    );
    expect(merged.pet?.xp).toBe(30);
    expect(Object.keys(merged.heatle ?? {})).toEqual(["2026-10-01", "2026-10-02"]);
    expect(merged.city).toBe("Patna");
  });

  it("refuses a file that is not a backup", () => {
    expect(Backup.safeParse({ app: "other", version: 1, exported: "", data: {} }).success).toBe(false);
    expect(Backup.safeParse({ app: "agninetra-live", version: 1, exported: "", data: { pet: { xp: -5 } } }).success).toBe(false);
  });
});
