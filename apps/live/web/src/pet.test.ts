import { describe, expect, it } from "vitest";
import { itemsAt, LEVELS, levelOf, nextLevelXp } from "./pet";

describe("Netu's levels", () => {
  it("start at one and rise at each threshold", () => {
    expect(levelOf(0)).toBe(1);
    expect(levelOf(9)).toBe(1);
    expect(levelOf(10)).toBe(2);
    expect(levelOf(10_000)).toBe(LEVELS.length);
  });

  it("unlock one item per level after the first, never losing one", () => {
    expect(itemsAt(1)).toEqual([]);
    expect(itemsAt(3)).toEqual(["sun cap", "sunglasses"]);
  });

  it("know the next threshold, and that the last level has none", () => {
    expect(nextLevelXp(12)).toBe(30);
    expect(nextLevelXp(10_000)).toBeNull();
  });
});
