import { describe, expect, it } from "vitest";
import { busyMonths, gesture } from "./swipe-logic";

describe("gesture", () => {
  it("ignores short drags", () => {
    expect(gesture(20, 10)).toBeNull();
  });
  it("reads right, left and up", () => {
    expect(gesture(150, 10)).toBe("industry");
    expect(gesture(-150, 10)).toBe("not industry");
    expect(gesture(10, -150)).toBe("unsure");
  });
  it("never labels a drag downwards", () => {
    expect(gesture(10, 150)).toBeNull();
  });
});

describe("busyMonths", () => {
  it("names a source active in every observed month", () => {
    expect(busyMonths([0, 0, 0, 0, 0, 3, 4, 5, 0, 9, 9, 0], [6, 7, 8, 10, 11])).toBe("every observed month (Jun, Jul, Aug, Oct, Nov)");
  });
  it("names the busiest months of a seasonal one", () => {
    expect(busyMonths([0, 0, 0, 0, 0, 0, 0, 0, 0, 7, 9, 0], [6, 7, 8, 10, 11])).toBe("mostly Nov, Oct; active in 2 of the 5 months observed");
  });
  it("ignores months the record does not cover", () => {
    expect(busyMonths([0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 13], [6, 7, 8, 10, 11])).toBe("no detections in the months observed");
  });
});
