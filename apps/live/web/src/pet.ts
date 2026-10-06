import { z } from "zod";
import { PetRecord } from "./records";
import { recall, remember } from "./store";

// Netu as a pet. Playing, never burning, earns it experience: points for seeing, rule 2.
// Its progress lives on this phone only.

export type PetState = z.infer<typeof PetRecord>;

export const REWARDS = { swipe: 1, swipeGoldRight: 2, heatlePlayed: 1, heatleSolved: 5 } as const;

// Experience needed to reach each level, and what Netu wears from that level on.
export const LEVELS: { xp: number; item: string | null }[] = [
  { xp: 0, item: null },
  { xp: 10, item: "sun cap" },
  { xp: 30, item: "sunglasses" },
  { xp: 60, item: "smog scarf" },
  { xp: 120, item: "explorer's hat" },
  { xp: 250, item: "golden eye" },
];

export function levelOf(xp: number): number {
  let level = 1;
  LEVELS.forEach((step, i) => {
    if (xp >= step.xp) level = i + 1;
  });
  return level;
}

export function itemsAt(level: number): string[] {
  return LEVELS.slice(0, level)
    .map((step) => step.item)
    .filter((item): item is string => item !== null);
}

export function nextLevelXp(xp: number): number | null {
  const next = LEVELS.find((step) => step.xp > xp);
  return next ? next.xp : null;
}

export function petState(): PetState {
  return recall("pet", (v) => PetRecord.parse(v), { xp: 0 });
}

export function award(kind: keyof typeof REWARDS): PetState {
  const state = { xp: petState().xp + REWARDS[kind] };
  remember("pet", state);
  window.dispatchEvent(new CustomEvent("netu-xp", { detail: state }));
  return state;
}
