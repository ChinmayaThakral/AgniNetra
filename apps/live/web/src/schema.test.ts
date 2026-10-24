import { describe, expect, it } from "vitest";
import { Boundaries, Cell, Feed } from "./schema";

const cell = {
  cell: "fixture-cell",
  centre: [75.55, 30.55],
  state: null,
  district: null,
  class: "unclassified",
  how_sure: "low",
  seen_by: ["polar"],
  evening: true,
  first_seen_ist: "16:30",
};

function evening(): Feed {
  return {
    schema: "agninetra-live/1",
    generated_utc: "2026-10-22T11:00:00Z",
    evening_ist: "2026-10-22",
    latency: { insat_newest_utc: null, insat_delay_hours: null, polar_newest_utc: null },
    match: {
      window_ist: "fixture",
      polar_share: null,
      insat_share: null,
      polar_last_seen_ist: null,
      insat_last_seen_ist: null,
      overs: [],
    },
    cells: [Cell.parse(cell)],
    districts: [],
    netu: [{ template: "quiet", text: "fixture" }],
    commentary: [],
    tomorrow: {
      city: "Delhi",
      forecast_date: "2026-10-23",
      pm25_24h_mean: null,
      cpcb_category: null,
      evening_fire_cells: 1,
      school_hybrid: "not measured",
      source: "fixture",
    },
    heatle: {
      clues: [{ kind: "place", centre: [75.55, 30.55], hint: { text: "fixture" } }],
      answer: "cannot tell",
      choices: ["cannot tell"],
    },
    wind: null,
    attribution: ["fixture"],
    caveats: ["fixture"],
  };
}

describe("feed schema", () => {
  it("preserves nullable fields, open clue records and omitted historical fields", () => {
    const input = evening();
    expect(Feed.parse(input)).toEqual(input);
    expect(Feed.parse(input).match).not.toHaveProperty("cells_total");
    expect(Feed.parse(input)).not.toHaveProperty("air");
  });

  it.each([
    { ...cell, extra: true },
    { ...cell, centre: [75.55] },
    { ...cell, how_sure: "high" },
    { ...cell, seen_by: ["other"] },
    { ...cell, first_seen_ist: "afternoon" },
  ])("rejects a malformed or expanded cell", (input) => {
    expect(Cell.safeParse(input).success).toBe(false);
  });

  it("rejects invalid bounded shares and missing required records", () => {
    const input = evening();
    expect(Feed.safeParse({ ...input, match: { ...input.match, polar_share: 1.1 } }).success).toBe(false);
    expect(Feed.safeParse({ ...input, heatle: { ...input.heatle, clues: [null] } }).success).toBe(false);
    expect(Feed.safeParse({ ...input, attribution: [] }).success).toBe(false);
    expect(Feed.safeParse({ ...input, latency: undefined }).success).toBe(false);
  });

  it("keeps valid optional air and wind tuples while rejecting invalid directions", () => {
    const input = {
      ...evening(),
      air: [{ city: "Delhi", pm25_24h_mean: null, cpcb_category: null }],
      wind: { grid_deg: 1, hours_ist: ["16:30"], points: [[75.55, 30.55, [[null, null], [2, 360]]]], source: "fixture" },
    };
    expect(Feed.parse(input)).toEqual(input);
    expect(Feed.safeParse({ ...input, wind: { ...input.wind, points: [[75.55, 30.55, [[2, 361]]]] } }).success).toBe(false);
  });
});

describe("boundary schema", () => {
  const ring = [[75, 30], [76, 30], [75, 30]];

  it.each([
    { type: "Polygon", coordinates: [ring] },
    { type: "MultiPolygon", coordinates: [[ring]] },
  ])("parses supported geometry and strips unused object fields", (geometry) => {
    const properties = { kind: "state", name: "fixture" };
    const value = { type: "FeatureCollection", attribution: "fixture", features: [{ properties, geometry }] };
    expect(Boundaries.parse({ ...value, extra: true })).toEqual(value);
  });

  it("rejects unsupported geometry and malformed coordinate tuples", () => {
    const value = {
      type: "FeatureCollection",
      attribution: "fixture",
      features: [{ properties: { kind: "state", name: "fixture" }, geometry: { type: "Point", coordinates: [75, 30] } }],
    };
    expect(Boundaries.safeParse(value).success).toBe(false);
    expect(Boundaries.safeParse({ ...value, features: [{ ...value.features[0], geometry: { type: "Polygon", coordinates: [[[75]]] } }] }).success).toBe(false);
  });
});
