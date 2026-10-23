import { beforeEach, describe, expect, it, vi } from "vitest";

const stored = vi.hoisted(() => new Map<string, unknown>());
const award = vi.hoisted(() => vi.fn());
vi.mock("./pet", () => ({ award }));
vi.mock("./store", () => ({
  recall: <T>(key: string, parse: (value: unknown) => T, fallback: T): T => stored.has(key) ? parse(stored.get(key)) : fallback,
  remember: (key: string, value: unknown): void => { stored.set(key, value); },
}));
import { recordDaily } from "./heatle";

beforeEach(() => { stored.clear(); award.mockClear(); });

describe("daily completion", () => {
  it("preserves history downloaded after a card was opened", () => {
    stored.set("heatle", { "2026-10-22": { solved: true, clue: 2 } });
    expect(recordDaily("2026-10-23", true, 3)).toEqual({
      "2026-10-22": { solved: true, clue: 2 },
      "2026-10-23": { solved: true, clue: 3 },
    });
    expect(award).toHaveBeenCalledExactlyOnceWith("heatleSolved");
  });

  it("preserves a synced completion and does not award it again", () => {
    const existing = { "2026-10-23": { solved: true, clue: 2 } };
    stored.set("heatle", existing);
    expect(recordDaily("2026-10-23", false, 6)).toEqual(existing);
    expect(award).not.toHaveBeenCalled();
  });

  it("records a daily loss once and preserves the first result", () => {
    recordDaily("2026-10-23", false, 6);
    recordDaily("2026-10-23", true, 2);
    expect(stored.get("heatle")).toEqual({ "2026-10-23": { solved: false, clue: 6 } });
    expect(award).toHaveBeenCalledExactlyOnceWith("heatlePlayed");
  });
});
