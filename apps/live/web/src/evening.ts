import { el, howSure, percent, plural } from "./dom";
import type { Feed } from "./schema";

// The evening analysis: which satellites saw the day's fires, told as one whole split three
// ways, with plain sentences built from the numbers. A cell both kinds of satellite saw is
// counted once, which is why the split always adds up to 100 percent.

export interface Split {
  total: number | null;
  polarOnly: number;
  both: number;
  insatOnly: number;
}

// The shares overlap: each is the part of all cells that group saw, so polar plus INSAT is
// 100 percent plus the part both saw. Undoing that overlap gives three parts that add to one.
export function splitOf(match: Feed["match"]): Split | null {
  const p = match.polar_share;
  const i = match.insat_share;
  if (p === null || i === null) return null;
  const total = match.cells_total ?? null;
  if (total && match.cells_both !== undefined) {
    const both = match.cells_both / total;
    return { total, both, polarOnly: Math.max(0, p - both), insatOnly: Math.max(0, i - both) };
  }
  const both = Math.max(0, p + i - 1);
  return { total, both, polarOnly: Math.max(0, 1 - i), insatOnly: Math.max(0, 1 - p) };
}

// Whole percentages that add to exactly 100, by giving the leftover points to the parts
// that lost the most in rounding.
export function wholePercents(shares: number[]): number[] {
  const raw = shares.map((x) => x * 100);
  const out = raw.map(Math.floor);
  const order = raw.map((x, i) => [x - Math.floor(x), i] as const).sort((a, b) => b[0] - a[0]);
  let left = 100 - out.reduce((a, b) => a + b, 0);
  for (const [, i] of order) {
    if (left <= 0) break;
    out[i] = (out[i] ?? 0) + 1;
    left -= 1;
  }
  return out;
}

function cellsText(pct: number, share: number, total: number | null): string {
  return total === null ? `${pct}%` : `${pct}%, ${plural(Math.round(share * total), "cell")}`;
}

export function istTime(utc: string | null): string | null {
  if (!utc) return null;
  const when = new Date(utc);
  if (Number.isNaN(when.getTime())) return null;
  return new Date(when.getTime() + 5.5 * 3_600_000).toISOString().slice(11, 16);
}

function todayIst(): string {
  return new Date(Date.now() + 5.5 * 3_600_000).toISOString().slice(0, 10);
}

// How the chosen evening is named in a sentence: "today", "yesterday", or its date, so the
// text always matches the day picked in the switcher.
export function dayWords(evening: string, today = todayIst()): { when: string; whose: string; title: string } {
  const yesterday = new Date(Date.parse(`${today}T00:00:00Z`) - 86_400_000).toISOString().slice(0, 10);
  if (evening === today) return { when: "today", whose: "today's", title: "today's" };
  if (evening === yesterday) return { when: "yesterday", whose: "yesterday's", title: "yesterday's" };
  const date = new Date(`${evening}T00:00:00Z`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  return { when: `on ${date}`, whose: `${date}'s`, title: `${date}'s` };
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// What Netu says at the top: the evening in three short lines anyone can read.
export function eveningLines(feed: Feed): string[] {
  const { match } = feed;
  const split = splitOf(match);
  const day = dayWords(feed.evening_ist);
  if (!split) return [day.when === "today" ? "A quiet sky so far today. No fire cells seen yet." : `A quiet sky ${day.when}. No fire cells were seen.`];
  const lines = [
    split.total === null
      ? `Polar satellites saw ${percent(match.polar_share)} of ${day.whose} fire cells and INSAT-3DS saw ${percent(match.insat_share)}.`
      : `${plural(split.total, "fire cell")} seen over India ${day.when}. Polar satellites saw ${percent(match.polar_share)} of them, INSAT-3DS ${percent(match.insat_share)}.`,
  ];
  const polarLast = match.polar_last_seen_ist;
  const insatLast = match.insat_last_seen_ist;
  if (polarLast && insatLast && insatLast > polarLast) {
    lines.push(`The last polar pass was at ${polarLast}. After that only INSAT-3DS was watching; it last saw a fire at ${insatLast}.`);
  } else if (polarLast) {
    lines.push(`The last polar pass was at ${polarLast}.`);
  }
  const delay = feed.latency.insat_delay_hours;
  if (delay !== null && delay >= 24) lines.push(`INSAT-3DS data here is ${plural(Math.round(delay / 24), "day")} old.`);
  return lines;
}

function halfHourLine(over: Feed["match"]["overs"][number], newest: string | null): string {
  if (newest === null || over.over > newest) return "INSAT-3DS data for this half hour has not arrived yet; it runs about an hour behind.";
  if (over.polar_new) return `A polar satellite passed over. Polar satellites have now seen ${percent(over.polar_share)}.`;
  if (over.insat_new) return `INSAT-3DS saw new fires. It has now seen ${percent(over.insat_share)}.`;
  return "No new fires seen.";
}

export function eveningCard(feed: Feed): HTMLElement {
  const { match } = feed;
  const card = el("section", "card evening");
  const day = dayWords(feed.evening_ist);
  card.append(el("h2", "", `Who saw ${day.title} fires`));
  card.append(el("p", "muted small", `${feed.evening_ist}, fires seen ${match.window_ist} IST, counted per 11 km cell.`));
  const split = splitOf(match);
  if (!split) {
    card.append(el("p", "big", day.when === "today" ? "No fire cells seen yet today." : `No fire cells were seen ${day.when}.`));
    return card;
  }
  if (split.total !== null) card.append(el("p", "big", plural(split.total, "fire cell")));

  const parts: [string, string, number][] = [
    ["polar", "Polar satellites only", split.polarOnly],
    ["both", "Both", split.both],
    ["insat", "INSAT-3DS only", split.insatOnly],
  ];
  const bar = el("div", "split-bar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", parts.map(([, name, share]) => `${name} ${percent(share)}`).join(", "));
  const key = el("ul", "split-key");
  const pcts = wholePercents(parts.map(([, , share]) => share));
  parts.forEach(([cls, name, share], index) => {
    const part = el("span", `split ${cls}`);
    part.style.flexGrow = String(share);
    bar.append(part);
    const item = el("li", "");
    item.append(el("span", `split-dot ${cls}`), el("span", "", name), el("strong", "", cellsText(pcts[index] ?? 0, share, split.total)));
    key.append(item);
  });
  card.append(bar, key);

  const polarLast = match.polar_last_seen_ist;
  card.append(
    el(
      "p",
      "explain",
      `Polar satellites see small fires, but only when they pass overhead${polarLast ? `; ${day.when} the last pass was at ${polarLast}` : ""}. INSAT-3DS sees only larger fires, but it looks every 30 minutes, day and night. The INSAT-3DS only part is fire the polar passes missed.`,
    ),
  );

  const newest = istTime(feed.latency.insat_newest_utc);
  const timeline = el("ol", "timeline");
  for (const over of match.overs) {
    const row = el("li", over.insat_new ? "half new" : "half");
    const meter = el("span", "half-meter");
    const fill = el("span", "half-fill");
    fill.style.width = `${Math.round((over.insat_share ?? 0) * 100)}%`;
    meter.append(fill);
    row.append(el("span", "half-time", over.over), meter, el("span", "half-text", halfHourLine(over, newest)));
    timeline.append(row);
  }
  card.append(el("h3", "", "The evening, half hour by half hour"), el("p", "muted small", `The bar is the share of ${day.whose} fire cells INSAT-3DS had seen by then.`), timeline);
  card.append(howSure("low", "Share of 11 km fire cells seen. Weak labels. Not an official count."));
  return card;
}

interface Satellite {
  name: string;
  who: string;
  sees: string;
  looks: string;
  share: number | null;
  last: string | null;
}

// Facts from the report: pixel sizes from the sensor specifications it cites, and the six
// polar look times from its own measurement over 601941 detections, in local solar time.
export function satellitesCard(feed: Feed): HTMLElement {
  const satellites: Satellite[] = [
    {
      name: "Polar satellites",
      who: "VIIRS on Suomi NPP, NOAA-20 and NOAA-21; MODIS on Terra and Aqua",
      sees: "Sharp: 375 m pixels for VIIRS, 1 km for MODIS",
      looks: "Six fixed passes a day, near 01:42, 02:48, 09:54, 13:12, 13:54 and 21:18 local solar time",
      share: feed.match.polar_share,
      last: feed.match.polar_last_seen_ist,
    },
    {
      name: "INSAT-3DS",
      who: "India's own geostationary weather satellite, read by this project's detector",
      sees: "Coarse: 4 km pixels, so only larger fires",
      looks: "Always over India: a picture every 30 minutes, day and night",
      share: feed.match.insat_share,
      last: feed.match.insat_last_seen_ist,
    },
  ];
  const wrap = el("section", "card satellites");
  wrap.append(el("h2", "", "The satellites"));
  const grid = el("div", "satellite-grid");
  for (const s of satellites) {
    const card = el("article", "satellite");
    card.append(
      el("h3", "", s.name),
      el("p", "small muted", s.who),
      el("p", "small", s.sees),
      el("p", "small", s.looks),
      el("p", "stat", `${capitalise(dayWords(feed.evening_ist).when)}: saw ${percent(s.share)} of fire cells${s.last ? `, last at ${s.last}` : ""}`),
    );
    grid.append(card);
  }
  wrap.append(grid);
  return wrap;
}
