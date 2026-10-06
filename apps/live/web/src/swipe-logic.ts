// The pure part of Swipe, kept apart from the page so it can be tested. Which candidate
// comes next, where the hidden gold questions go, and how a player's eye is scored.

export type Answer = "factory" | "flare" | "unsure";

export interface SwipeItem {
  id: string;
  chip: string;
  acquired: string;
  gold: "factory" | "flare" | null;
}

export interface Given {
  a: Answer;
  at: string;
}

// A small seeded generator, so the order is the same for a player all day and differs
// between days, with no randomness the tests cannot repeat.
export function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function shuffled<T>(items: T[], random: () => number): T[] {
  const out = [...items];
  for (let i = out.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j] as T, out[i] as T];
  }
  return out;
}

export const GOLD_EVERY = 5;

// Unanswered items in a daily order, with one unanswered gold question in every
// GOLD_EVERY places while any remain, so a player meets them without knowing which.
export function queue(items: SwipeItem[], answered: Record<string, Given>, seed: number): SwipeItem[] {
  const random = seeded(seed);
  const open = items.filter((item) => !(item.id in answered));
  const gold = shuffled(open.filter((item) => item.gold !== null), random);
  const plain = shuffled(open.filter((item) => item.gold === null), random);
  const out: SwipeItem[] = [];
  while (gold.length || plain.length) {
    const goldTurn = out.length % GOLD_EVERY === GOLD_EVERY - 1;
    const next = (goldTurn ? gold.shift() : plain.shift()) ?? gold.shift() ?? plain.shift();
    if (next) out.push(next);
  }
  return out;
}

// How many known sites the player has seen, and how many they got right. "Not sure" on
// a gold question is honest, so it counts as seen and not as wrong or right.
export function goldScore(items: SwipeItem[], answered: Record<string, Given>): { seen: number; right: number; judged: number } {
  let seen = 0;
  let right = 0;
  let judged = 0;
  for (const item of items) {
    const given = answered[item.id];
    if (!item.gold || !given) continue;
    seen += 1;
    if (given.a === "unsure") continue;
    judged += 1;
    if (given.a === item.gold) right += 1;
  }
  return { seen, right, judged };
}

// A swipe on a touch screen: far enough right is factory, up is flare, left is not sure.
export function gesture(dx: number, dy: number, threshold = 60): Answer | null {
  if (-dy > threshold && Math.abs(dy) > Math.abs(dx)) return "flare";
  if (dx > threshold) return "factory";
  if (dx < -threshold) return "unsure";
  return null;
}
