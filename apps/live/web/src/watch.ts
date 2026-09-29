import "./style.css";
import { el, percent } from "./dom";
import { drawFireMap } from "./fire-map";
import { moodOf, netuSvg } from "./netu";
import { NORTH_INDIA } from "./projection";
import { Boundaries, Feed } from "./schema";

// The Watch Party screen, for a stream: 16:9, no controls, the Fire Clock looping over the
// day, the score and the latest commentary. It re-reads the feed every five minutes, so
// one browser source can run the whole evening. Nothing here differs from the app in what
// it shows; it only lays it out for a broadcast.

const REFRESH_MS = 5 * 60 * 1000;
const FRAME_MS = 600;

function slots(): string[] {
  const out: string[] = [];
  for (let h = 10; h < 20; h += 1) {
    const hh = String(h).padStart(2, "0");
    out.push(`${hh}:00`, `${hh}:30`);
  }
  return out;
}

async function readFeed(): Promise<Feed> {
  const response = await fetch("feed/latest.json", { cache: "no-cache" });
  if (!response.ok) throw new Error(`feed: HTTP ${response.status}`);
  return Feed.parse(await response.json());
}

async function start(): Promise<void> {
  const root = document.getElementById("watch");
  if (!root) return;
  const boundaries = Boundaries.parse(await (await fetch("data/boundaries.json")).json());
  let feed = await readFeed();

  const canvas = el("canvas", "watch-map");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Fire Clock map of North India, replaying the evening's fire cells.");
  const side = el("aside", "watch-side");
  const clock = el("p", "watch-clock", "");
  root.replaceChildren(canvas, side);

  const paintSide = (): void => {
    const score = el("div", "watch-score");
    score.append(
      el("p", "watch-team polar", `Polar ${percent(feed.match.polar_share)}`),
      el("p", "watch-team insat", `INSAT ${percent(feed.match.insat_share)}`),
      el("p", "muted", "share of today's fire cells each caught"),
    );
    const lines = el("ol", "commentary");
    for (const line of feed.commentary.slice(-4)) lines.append(el("li", "", line.text));
    side.replaceChildren(
      netuSvg(moodOf(feed), 120),
      el("h1", "", "AgniNetra Watch Party"),
      el("p", "muted", feed.evening_ist),
      score,
      clock,
      lines,
      el("p", "caveat", "how sure: low. Weak labels. Not an official count."),
      el("p", "small muted", "Data Source MOSDAC/SAC/ISRO. NASA FIRMS. Boundaries (c) OpenStreetMap contributors, ODbL."),
    );
  };
  paintSide();

  const frames = slots();
  let i = 0;
  window.setInterval(() => {
    const now = frames[i % frames.length];
    clock.textContent = now ? `Fire Clock ${now} IST` : "";
    drawFireMap(canvas, boundaries, feed.cells, { bounds: NORTH_INDIA, clock: now });
    i += 1;
  }, FRAME_MS);

  window.setInterval(() => {
    readFeed()
      .then((fresh) => {
        feed = fresh;
        paintSide();
      })
      .catch(() => undefined);
  }, REFRESH_MS);
}

void start();
