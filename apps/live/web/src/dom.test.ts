import { describe, expect, it } from "vitest";
import { plural } from "./dom";

describe("plural", () => {
  it("keeps the noun singular for exactly one", () => {
    expect(plural(1, "evening")).toBe("1 evening");
    expect(plural(0, "day")).toBe("0 days");
    expect(plural(2, "hot spot")).toBe("2 hot spots");
  });
});
