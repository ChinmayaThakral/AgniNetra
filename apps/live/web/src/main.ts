import "./style.css";
import { el, howSure } from "./dom";
import { CLASS_COLOURS, CLASS_LABELS, drawFireMap } from "./fire-map";
import { heatleCard } from "./heatle";
import { matchBoard } from "./match-board";
import { moodOf, netuSvg } from "./netu";
import { itemsAt, levelOf, petState } from "./pet";
import { petCard } from "./pet-card";
import { playerCards } from "./player-cards";
import { VisitRecord } from "./records";
import { fit, INDIA, NORTH_INDIA, type Bounds } from "./projection";
import { z } from "zod";
import { Boundaries, Feed } from "./schema";
import { matchShareCard, shareCanvas } from "./share-card";
import { smokeCard } from "./smoke-card";
import { SwipePack, swipeCard } from "./swipe";
import { recall, remember } from "./store";
import { cityAir, tomorrowCard } from "./tomorrow-card";
import type { Point } from "./upwind";
import { Season, wrappedCard, wrappedTime } from "./wrapped";

async function load<T>(path: string, parse: (value: unknown) => T): Promise<T> {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return parse(await response.json());
}

function failure(root: HTMLElement, message: string): void {
  root.replaceChildren(el("p", "card", `The feed could not be read: ${message}`));
}

async function start(): Promise<void> {
  const root = document.getElementById("app");
  if (!root) return;
  let feed: Feed;
  let boundaries: Boundaries;
  try {
    [feed, boundaries] = await Promise.all([
      load("feed/latest.json", (v) => Feed.parse(v)),
      load("data/boundaries.json", (v) => Boundaries.parse(v)),
    ]);
  } catch (error) {
    failure(root, error instanceof Error ? error.message : "unknown error");
    return;
  }
  // Swipe is extra: without its pack the evening still loads, just without the game.
  const swipe = await load("game/swipe.json", (v) => SwipePack.parse(v)).catch(() => null);
  const season = await load("feed/season.json", (v) => Season.parse(v)).catch(() => null);

  // The city Netu follows is remembered on this phone only.
  const cities = feed.air?.map((a) => a.city) ?? [feed.tomorrow.city];
  const fallbackCity = cities[0] ?? feed.tomorrow.city;
  let city = recall("city", (v) => z.string().parse(v), fallbackCity);
  if (!cities.includes(city)) city = fallbackCity;

  // Each day the app is opened is kept on this phone with the city's forecast category,
  // which Smog Wrapped counts in December.
  const recordVisit = (): void => {
    const visits = recall("visits", (v) => VisitRecord.parse(v), {});
    remember("visits", { ...visits, [feed.evening_ist]: cityAir(feed, city).category });
  };
  recordVisit();
  const wearing = (): string[] => itemsAt(levelOf(petState().xp));

  const header = el("header", "top");
  let netu = netuSvg(moodOf(feed, city), 88, wearing());
  header.append(netu);
  window.addEventListener("netu-xp", () => {
    const next = netuSvg(moodOf(feed, city), 88, wearing());
    netu.replaceWith(next);
    netu = next;
  });
  const lines = el("div", "netu-lines");
  for (const line of feed.netu) lines.append(el("p", "netu-line", line.text));
  const picker = el("label", "city-picker", "Netu follows the air in");
  const select = el("select", "");
  for (const name of cities) {
    const option = el("option", "", name);
    option.value = name;
    select.append(option);
  }
  select.value = city;
  picker.append(select);
  lines.append(picker);
  header.append(lines);
  let tomorrow = tomorrowCard(feed, city);
  select.addEventListener("change", () => {
    city = select.value;
    remember("city", city);
    recordVisit();
    const nextNetu = netuSvg(moodOf(feed, city), 88, wearing());
    netu.replaceWith(nextNetu);
    netu = nextNetu;
    const nextTomorrow = tomorrowCard(feed, city);
    tomorrow.replaceWith(nextTomorrow);
    tomorrow = nextTomorrow;
  });

  const mapCard = el("section", "card map-card");
  const canvas = el("canvas", "fire-map");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Map of today's fire cells over India, each an 11 km square. The match scores above give the same shares in text.");
  const controls = el("div", "map-controls");
  let bounds: Bounds = NORTH_INDIA;
  let eveningOnly = false;
  let ring: [number, number] | null = null;
  let clock: string | undefined;
  let path: Point[] | undefined;
  const redraw = (): void => {
    drawFireMap(canvas, boundaries, feed.cells, { bounds, untilEvening: eveningOnly, clock, path });
    if (ring) {
      const ctx = canvas.getContext("2d");
      const projection = fit(bounds, canvas.clientWidth, canvas.clientHeight);
      const [x, y] = projection.point(ring[0], ring[1]);
      if (ctx) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(x, y, 14, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
  };
  const toggle = (label: string, action: () => void): HTMLButtonElement => {
    const button = el("button", "button", label);
    button.addEventListener("click", () => {
      action();
      redraw();
    });
    return button;
  };
  controls.append(
    toggle("North India", () => (bounds = NORTH_INDIA)),
    toggle("All India", () => (bounds = INDIA)),
    toggle("Evening only", () => (eveningOnly = !eveningOnly)),
  );
  const clockLabel = el("span", "clock-label", "");
  const play = el("button", "button", "Play the Fire Clock");
  play.addEventListener("click", () => {
    const slots: string[] = [];
    for (let h = 10; h < 20; h += 1) slots.push(`${String(h).padStart(2, "0")}:00`, `${String(h).padStart(2, "0")}:30`);
    let i = 0;
    const tick = (): void => {
      clock = slots[i];
      clockLabel.textContent = clock ? `${clock} IST` : "";
      redraw();
      i += 1;
      if (i < slots.length) window.setTimeout(tick, 350);
      else {
        clock = undefined;
        clockLabel.textContent = "full day";
        redraw();
      }
    };
    tick();
  });
  controls.append(play, clockLabel);
  const legend = el("ul", "legend");
  for (const key of Object.keys(CLASS_LABELS) as (keyof typeof CLASS_LABELS)[]) {
    const item = el("li", "");
    const swatch = el("span", "swatch");
    swatch.style.background = CLASS_COLOURS[key];
    item.append(swatch, document.createTextNode(CLASS_LABELS[key]));
    legend.append(item);
  }
  mapCard.append(canvas, controls, legend, howSure("low"));

  const smoke = smokeCard(feed, (trace) => {
    path = trace;
    redraw();
  });
  canvas.addEventListener("click", (event) => {
    const box = canvas.getBoundingClientRect();
    const projection = fit(bounds, canvas.clientWidth, canvas.clientHeight);
    smoke.trace(projection.invert(event.clientX - box.left, event.clientY - box.top));
  });

  const share = el("button", "button share", "Share the match");
  share.addEventListener("click", () => {
    void shareCanvas(matchShareCard(feed, canvas), `agninetra-${feed.evening_ist}.png`);
  });

  const footer = el("footer", "credits");
  for (const text of feed.caveats) footer.append(el("p", "caveat", text));
  for (const text of [...feed.attribution, boundaries.attribution]) footer.append(el("p", "", text));
  footer.append(el("p", "", `Feed built ${feed.generated_utc} UTC.`));

  root.replaceChildren(
    header,
    ...(season && wrappedTime(feed.evening_ist, window.location.search) ? [wrappedCard(season, city)] : []),
    matchBoard(feed),
    playerCards(feed),
    mapCard,
    share,
    smoke.card,
    tomorrow,
    heatleCard(feed, (centre) => {
      ring = centre;
      bounds = INDIA;
      redraw();
    }),
    ...(swipe ? [swipeCard(swipe, feed.evening_ist)] : []),
    petCard(() => moodOf(feed, city)),
    footer,
  );
  redraw();
  window.addEventListener("resize", redraw);
}

void start();

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register("sw.js");
}
