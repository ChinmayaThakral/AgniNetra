import { describe, expect, it } from "vitest";
import { GOLD_EVERY, gesture, goldScore, queue, type Given, type SwipeItem } from "./swipe-logic";

function at<T>(list: T[], i: number): T {
  const value = list[i];
  if (value === undefined) throw new Error(`no item at ${i}`);
  return value;
}

const items: SwipeItem[] = Array.from({ length: 12 }, (_, i) => ({
  id: `s${String(i).padStart(10, "0")}`,
  chip: `chips/s${String(i).padStart(10, "0")}.webp`,
  acquired: "2026-04-21",
  gold: i < 2 ? "factory" : null,
}));

describe("queue", () => {
  it("is the same all day and different on another day", () => {
    expect(queue(items, {}, 20261006).map((i) => i.id)).toEqual(queue(items, {}, 20261006).map((i) => i.id));
    expect(queue(items, {}, 20261006).map((i) => i.id)).not.toEqual(queue(items, {}, 20261007).map((i) => i.id));
  });

  it("never offers an answered item again", () => {
    const answered: Record<string, Given> = { [at(items, 5).id]: { a: "factory", at: "t" } };
    expect(queue(items, answered, 1).some((i) => i.id === at(items, 5).id)).toBe(false);
  });

  it("puts a gold question in every fifth place while any remain", () => {
    const order = queue(items, {}, 3);
    expect(order).toHaveLength(items.length);
    expect(at(order, GOLD_EVERY - 1).gold).toBe("factory");
    expect(at(order, 2 * GOLD_EVERY - 1).gold).toBe("factory");
  });
});

describe("goldScore", () => {
  it("counts not sure as seen, never as right or wrong", () => {
    const answered: Record<string, Given> = {
      [at(items, 0).id]: { a: "factory", at: "t" },
      [at(items, 1).id]: { a: "unsure", at: "t" },
      [at(items, 2).id]: { a: "flare", at: "t" },
    };
    expect(goldScore(items, answered)).toEqual({ seen: 2, right: 1, judged: 1 });
  });
});

describe("gesture", () => {
  it("reads right, up and left, and ignores a short drag", () => {
    expect(gesture(120, 10)).toBe("factory");
    expect(gesture(10, -120)).toBe("flare");
    expect(gesture(-120, 5)).toBe("unsure");
    expect(gesture(20, -20)).toBeNull();
  });
});
