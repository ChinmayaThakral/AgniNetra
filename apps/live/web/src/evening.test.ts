import { describe, expect, it } from "vitest";
import { istTime, splitOf, wholePercents } from "./evening";

const base = { window_ist: "10:00 to 20:00", polar_last_seen_ist: "13:54", insat_last_seen_ist: "18:30", overs: [] };

describe("splitOf", () => {
  it("turns two overlapping shares into three parts that add to one", () => {
    const split = splitOf({ ...base, polar_share: 0.769, insat_share: 0.254 });
    expect(split).not.toBeNull();
    if (!split) return;
    expect(split.both).toBeCloseTo(0.023, 3);
    expect(split.polarOnly).toBeCloseTo(0.746, 3);
    expect(split.insatOnly).toBeCloseTo(0.231, 3);
    expect(split.polarOnly + split.both + split.insatOnly).toBeCloseTo(1, 6);
  });
  it("uses the counts when the feed carries them", () => {
    const split = splitOf({ ...base, polar_share: 0.75, insat_share: 0.3, cells_total: 200, cells_both: 10 });
    expect(split?.total).toBe(200);
    expect(split?.both).toBeCloseTo(0.05, 6);
    expect(split?.insatOnly).toBeCloseTo(0.25, 6);
  });
  it("says nothing when a share is not measured", () => {
    expect(splitOf({ ...base, polar_share: null, insat_share: 0.3 })).toBeNull();
  });
});

describe("istTime", () => {
  it("reads a UTC instant as IST", () => {
    expect(istTime("2026-10-05T12:30:00+00:00")).toBe("18:00");
    expect(istTime(null)).toBeNull();
  });
});

describe("wholePercents", () => {
  it("always adds to 100", () => {
    expect(wholePercents([0.7584, 0.026, 0.2156])).toEqual([76, 3, 21]);
    expect(wholePercents([1 / 3, 1 / 3, 1 / 3]).reduce((a, b) => a + b, 0)).toBe(100);
  });
});
