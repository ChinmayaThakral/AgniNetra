// Dates as the feed writes them, YYYY-MM-DD in IST, and the streaks counted over them.

const DAY_MS = 86_400_000;

export function previousDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, d ?? 1) - DAY_MS).toISOString().slice(0, 10);
}

// Consecutive days ending today on which something was recorded.
export function streakOf(days: Record<string, unknown>, today: string): number {
  let streak = 0;
  for (let day = today; day in days; day = previousDay(day)) streak += 1;
  return streak;
}

// The longest run of consecutive recorded days.
export function bestStreak(days: Record<string, unknown>): number {
  let best = 0;
  for (const day of Object.keys(days)) {
    if (previousDay(day) in days) continue;
    let run = 0;
    for (let d = day; d in days; ) {
      run += 1;
      const [y, m, dd] = d.split("-").map(Number);
      d = new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, dd ?? 1) + DAY_MS).toISOString().slice(0, 10);
    }
    best = Math.max(best, run);
  }
  return best;
}
