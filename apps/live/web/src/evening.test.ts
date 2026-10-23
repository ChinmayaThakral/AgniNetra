import { afterEach, describe, expect, it, vi } from "vitest";
import { dayWords, eveningCard, eveningLines, halfHourLine, istTime, splitOf, wholePercents } from "./evening";
import type { Feed } from "./schema";

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

describe("dayWords", () => {
  it("names the chosen evening relative to today", () => {
    expect(dayWords("2026-10-07", "2026-10-07").when).toBe("today");
    expect(dayWords("2026-10-06", "2026-10-07").title).toBe("yesterday's");
    expect(dayWords("2026-10-05", "2026-10-07").when).toBe("on Mon, 5 Oct");
  });
});

function feed(match: Partial<Feed["match"]> = {}): Feed {
  return {
    schema: "agninetra-live/1",
    generated_utc: "2026-10-23T14:30:00Z",
    evening_ist: "2026-10-23",
    latency: { insat_newest_utc: "2026-10-23T14:00:00Z", insat_delay_hours: 1, polar_newest_utc: null },
    match: { ...base, polar_share: 0.2, insat_share: 0.9, cells_total: 10, cells_both: 1, ...match },
    cells: [],
    districts: [],
    netu: [],
    commentary: [],
    tomorrow: { city: "Delhi", forecast_date: "2026-10-24", pm25_24h_mean: null, cpcb_category: null, evening_fire_cells: 0, school_hybrid: "not measured", source: "test" },
    heatle: { clues: [], answer: "cannot tell", choices: ["cannot tell"] },
    wind: null,
    attribution: ["test"],
    caveats: ["Weak labels."],
  };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("eveningLines", () => {
  it("reports detection times without inferring passes or exclusive watching", () => {
    const lines = eveningLines(feed());
    const text = lines.join(" ");
    expect(text).toContain("last polar fire detection in this feed was at 13:54");
    expect(text).toContain("INSAT-3DS detected fires later, most recently at 18:30");
    expect(text).not.toMatch(/pass|watching|afternoon|missed/i);
    expect(text).toContain("20%");
    expect(text).toContain("90%");
  });

  it("still calls a late polar detection a detection when INSAT was earlier", () => {
    const text = eveningLines(feed({ polar_last_seen_ist: "19:40" })).join(" ");
    expect(text).toContain("last polar fire detection in this feed was at 19:40");
    expect(text).not.toContain("detected fires later");
    expect(text).not.toMatch(/pass|watching|afternoon|missed/i);
  });

  it("does not invent an afternoon detection when no polar fires were detected", () => {
    const text = eveningLines(feed({ polar_share: 0, insat_share: 1, polar_last_seen_ist: null, cells_both: 0 })).join(" ");
    expect(text).toContain("Polar satellites saw 0%");
    expect(text).not.toMatch(/last polar|afternoon|pass|watching/i);
  });

  it.each(["2026-10-23", "2026-10-22"])("describes an empty feed on %s without claiming a quiet sky", (evening) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-23T14:30:00Z"));
    const empty = feed({ polar_share: null, insat_share: null, polar_last_seen_ist: null, insat_last_seen_ist: null, cells_total: 0, cells_both: 0 });
    empty.evening_ist = evening;
    const text = eveningLines(empty).join(" ");
    expect(text).toContain("No fire cells detected in this feed");
    expect(text).not.toMatch(/quiet sky/i);
  });

  it("keeps the data age warning", () => {
    const delayed = feed();
    delayed.latency.insat_delay_hours = 72;
    expect(eveningLines(delayed)).toContain("INSAT-3DS data here is 3 days old.");
  });
});

describe("halfHourLine", () => {
  const over = { over: "19:30", polar_share: 0.2, insat_share: 0.9, polar_new: true, insat_new: true };

  it("describes polar detections in the bucket without inferring an orbital pass", () => {
    const text = halfHourLine(over, "19:30");
    expect(text).toBe("Polar satellites detected fires this half hour. They have now seen 20%.");
    expect(text).not.toMatch(/pass|watching|afternoon|missed/i);
  });

  it.each([null, "19:00"])("keeps missing or delayed INSAT data ahead of detection copy (%s)", (newest) => {
    expect(halfHourLine(over, newest)).toContain("data for this half hour has not arrived yet");
  });

  it("reports INSAT detections when polar has none in the half hour", () => {
    expect(halfHourLine({ ...over, polar_new: false }, "19:30")).toBe("INSAT-3DS detected fires this half hour. It has now seen 90%.");
  });

  it("limits an empty half hour to the feed's detections", () => {
    expect(halfHourLine({ ...over, polar_new: false, insat_new: false }, "19:30")).toBe("No new fires detected in this feed this half hour.");
  });
});

class TextElement {
  textContent = "";
  style: Record<string, string> = {};

  append(...children: TextElement[]): void {
    this.textContent += children.map((child) => child.textContent).join(" ");
  }

  setAttribute(): void {}
}

describe("eveningCard explanation", () => {
  it.each(["19:40", null])("defines INSAT-only as observed cells in the feed, with polar last %s", (polarLast) => {
    vi.stubGlobal("document", { createElement: () => new TextElement() });
    const text = eveningCard(feed({ polar_last_seen_ist: polarLast })).textContent ?? "";
    expect(text).toContain("The INSAT-3DS only part is cells observed by INSAT-3DS but not by polar satellites in this feed.");
    expect(text).not.toMatch(/last polar pass|last pass was|passes missed|only INSAT-3DS was watching/i);
    if (polarLast) {
      expect(text).toContain(`The last polar fire detection in this feed was at ${polarLast}.`);
    } else {
      expect(text).not.toContain("last polar fire detection");
      expect(text).not.toContain("afternoon");
    }
  });
});
