import { describe, expect, it } from "vitest";
import type { Cell, Wind } from "./schema";
import { backTrajectory, stepUpwind, upwindSources } from "./upwind";

// A steady westerly: wind from 270 degrees at 20 km/h everywhere, for seven hours.
const westerly: Wind = {
  grid_deg: 1.5,
  hours_ist: ["10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00"],
  points: [[77.0, 28.5, Array.from({ length: 7 }, () => [20, 270] as [number, number])]],
  source: "test",
};

function cell(lon: number, lat: number, name: string): Cell {
  return {
    cell: name,
    centre: [lon, lat],
    state: "Haryana",
    district: name,
    class: "agricultural",
    how_sure: "low",
    seen_by: ["insat"],
    evening: true,
    first_seen_ist: "16:00",
  };
}

describe("upwind", () => {
  it("steps against the wind, toward where it blows from", () => {
    const [lon, lat] = stepUpwind([77, 28.5], 20, 270);
    expect(lon).toBeLessThan(77);
    expect(lat).toBeCloseTo(28.5, 6);
  });

  it("traces six hours back along a steady wind", () => {
    const path = backTrajectory([77, 28.5], westerly);
    expect(path).toHaveLength(7);
    const last = path[6];
    expect(last?.[0]).toBeLessThan(76);
  });

  it("finds fires upwind and ignores fires downwind", () => {
    const upwind = cell(76.5, 28.5, "upwind");
    const downwind = cell(77.5, 28.5, "downwind");
    const { sources } = upwindSources([77, 28.5], westerly, [downwind, upwind]);
    expect(sources.map((s) => s.cell.cell)).toEqual(["upwind"]);
    expect(sources[0]?.distanceKm).toBeGreaterThan(40);
  });

  it("ignores fires well outside the corridor", () => {
    const off = cell(76.5, 29.5, "north");
    expect(upwindSources([77, 28.5], westerly, [off]).sources).toHaveLength(0);
  });
});
