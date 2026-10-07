import "./style.css";
import { z } from "zod";
import { allowedDays, applyTheme, chosenDay, currentTheme, dayNav, siteLinks, tabs, themeButton } from "./chrome";
import { finishSignIn } from "./community";
import { el } from "./dom";
import { eveningCard, eveningLines, satellitesCard } from "./evening";
import { HeatlePack, heatleCard } from "./heatle";
import { mapView } from "./map-view";
import { moodOf, netuSvg } from "./netu";
import { itemsAt, levelOf, petState } from "./pet";
import { petCard } from "./pet-card";
import { placeCard } from "./place";
import { around } from "./projection";
import { VisitRecord } from "./records";
import { Boundaries, Feed } from "./schema";
import { recall, remember } from "./store";
import { swipeCard } from "./swipe";
import { syncButton } from "./sync";
import { cityAir } from "./city-air";
import { Season, wrappedCard, wrappedTime } from "./wrapped";

// The page is being left, by a day switch or a reload; requests the browser cancels then
// are not failures worth showing.
let leaving = false;
window.addEventListener("pagehide", () => (leaving = true));
window.addEventListener("pageshow", () => (leaving = false));

// A request can be cut off by a flaky connection or by the browser swapping in a new app
// version mid load, so each is tried a few times, waiting a little longer each time, and
// given up on after 20 seconds.
async function load<T>(path: string, parse: (value: unknown) => T, tries = 3): Promise<T> {
  for (let attempt = 1; ; attempt += 1) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 20_000);
    try {
      const response = await fetch(path, { cache: "no-cache", signal: controller.signal });
      if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
      return parse(await response.json());
    } catch (error) {
      if (attempt >= tries || leaving) throw error;
      await new Promise((resolve) => window.setTimeout(resolve, 600 * attempt));
    } finally {
      window.clearTimeout(timer);
    }
  }
}

function failure(root: HTMLElement, message: string): void {
  if (leaving) return;
  const loader = document.getElementById("loader");
  if (loader) loader.hidden = true;
  const screen = el("div", "error-screen");
  screen.setAttribute("role", "alert");
  const again = el("button", "button primary", "Try again");
  again.addEventListener("click", () => {
    again.disabled = true;
    if (loader) loader.hidden = false;
    window.location.reload();
  });
  const details = el("details", "error-details");
  details.append(el("summary", "", "Details"), el("p", "", message));
  screen.append(
    netuSvg("worried", 84),
    el("span", "shadow"),
    el("p", "error-title", "Netu could not fetch the evening."),
    el("p", "muted", "Usually a dropped connection. Trying again normally works."),
    again,
    details,
  );
  root.replaceChildren(screen);
}

async function start(): Promise<void> {
  const root = document.getElementById("app");
  if (!root) return;
  applyTheme(currentTheme());
  // Google returns here after a sign in; the token is handed to the server and wiped from
  // the address bar before anything else runs.
  await finishSignIn().catch(() => null);
  let feed: Feed;
  let boundaries: Boundaries;
  let latest: string;
  try {
    [feed, boundaries] = await Promise.all([
      load("feed/latest.json", (v) => Feed.parse(v)),
      load("data/boundaries.json", (v) => Boundaries.parse(v)),
    ]);
    latest = feed.evening_ist;
    const day = chosenDay(window.location.search, latest);
    if (day !== latest) feed = await load(`feed/${day}.json`, (v) => Feed.parse(v));
  } catch (error) {
    failure(root, error instanceof Error ? error.message : "unknown error");
    return;
  }
  const viewingToday = feed.evening_ist === latest;
  // Which of the two evenings before today the server still has, so a missing one is shown
  // as missing rather than as a link that fails.
  const held = await load("feed/days.json", (v) => z.array(z.string()).parse(v)).catch(() => [latest]);
  const available = new Set([latest, ...held.filter((day) => allowedDays(latest).includes(day))]);
  const season = await load("feed/season.json", (v) => Season.parse(v)).catch(() => null);
  const practice = await load("game/heatle.json", (v) => HeatlePack.parse(v)).catch(() => null);

  const cities = feed.air?.map((a) => a.city) ?? [feed.tomorrow.city];
  const fallbackCity = cities[0] ?? feed.tomorrow.city;
  let city = recall("city", (v) => z.string().parse(v), fallbackCity);
  if (!cities.includes(city)) city = fallbackCity;

  // Each day the app is opened is kept with the city's forecast category, which Smog
  // Wrapped counts in December.
  const recordVisit = (): void => {
    if (!viewingToday) return;
    const visits = recall("visits", (v) => VisitRecord.parse(v), {});
    remember("visits", { ...visits, [feed.evening_ist]: cityAir(feed, city).category });
  };
  recordVisit();
  const wearing = (): string[] => itemsAt(levelOf(petState().xp));

  const header = el("header", "top");
  let netu = netuSvg(moodOf(feed, city), 88, wearing());
  const repaintNetu = (): void => {
    const next = netuSvg(moodOf(feed, city), 88, wearing());
    netu.replaceWith(next);
    netu = next;
  };
  // Netu in the header is also the door to its pet card: hover on a desktop, tap on a
  // phone, Escape or a tap elsewhere to close.
  const netuButton = el("button", "netu-button");
  netuButton.type = "button";
  netuButton.setAttribute("aria-label", "Your Netu: level, points and what it wears");
  netuButton.setAttribute("aria-expanded", "false");
  netuButton.append(netu);
  const pop = el("div", "netu-pop");
  pop.hidden = true;
  pop.append(petCard(() => moodOf(feed, city)));
  const netuBox = el("div", "netu-box");
  netuBox.append(netuButton, pop);
  let closeTimer: number | undefined;
  const openPop = (open: boolean): void => {
    window.clearTimeout(closeTimer);
    pop.hidden = !open;
    netuButton.setAttribute("aria-expanded", String(open));
  };
  netuBox.addEventListener("mouseenter", () => openPop(true));
  netuBox.addEventListener("mouseleave", () => (closeTimer = window.setTimeout(() => openPop(false), 250)));
  netuButton.addEventListener("click", () => openPop(pop.hidden));
  document.addEventListener("click", (event) => {
    if (!pop.hidden && event.target instanceof Node && !netuBox.contains(event.target)) openPop(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") openPop(false);
  });
  header.append(netuBox);
  window.addEventListener("netu-xp", repaintNetu);
  const lines = el("div", "netu-lines");
  lines.append(el("p", "brand", "AgniNetra Live, the evening fire analysis"));
  for (const line of eveningLines(feed)) lines.append(el("p", "netu-line", line));
  header.append(lines);
  const tools = el("div", "top-tools");
  const blob = el("div", "tool-blob");
  blob.append(themeButton(), syncButton());
  tools.append(dayNav(latest, feed.evening_ist, available), blob, siteLinks());
  header.append(tools);

  const map = mapView(boundaries, feed.cells, (at) => place.showPoint(at, "This point"));
  const place = placeCard(feed, city, {
    focus: (bounds) => map.focus(bounds),
    setMarks: (marks) => map.setMarks(marks),
    setPath: (path) => map.setPath(path),
    onCity: (name) => {
      city = name;
      remember("city", city);
      window.dispatchEvent(new Event("agninetra-data"));
      recordVisit();
      repaintNetu();
    },
  });
  const pointAt = (at: [number, number], label: string): void => {
    map.setMarks([{ at, label }]);
    map.focus(around(at, 400));
    map.card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const footer = el("details", "credits");
  footer.append(el("summary", "", "Sources, credits and caveats"));
  for (const text of feed.caveats) footer.append(el("p", "caveat", text));
  for (const text of [...feed.attribution, boundaries.attribution]) footer.append(el("p", "", text));
  footer.append(el("p", "", `Feed built ${feed.generated_utc} UTC.`));

  // On a wide screen the page is one dashboard of three columns, each scrolling on its own;
  // on a phone the same columns simply stack.
  const story = el("div", "column");
  story.append(
    ...(season && wrappedTime(feed.evening_ist, window.location.search) ? [wrappedCard(season, city)] : []),
    eveningCard(feed),
    place.card,
    satellitesCard(feed),
  );
  const mapColumn = el("div", "column map-column");
  mapColumn.append(map.card);
  // Heatle and its qualifying rounds sit together: the daily puzzle and practice teach the
  // eye, the qualifying rounds below it are what unlock Swipe.
  const heatleTab = el("div", "tab-stack");
  heatleTab.append(heatleCard(feed, practice, (centre) => pointAt(centre, "Heatle site")), swipeCard(pointAt, "qualify"));
  const games: [string, HTMLElement][] = [
    ["Heatle", heatleTab],
    ["Swipe", swipeCard(pointAt)],
  ];
  const playColumn = el("div", "column");
  playColumn.append(tabs(games, "tab"), footer);
  const dashboard = el("div", "dashboard");
  dashboard.append(story, mapColumn, playColumn);
  root.replaceChildren(header, dashboard);
  map.redraw();
  const loader = document.getElementById("loader");
  if (loader) loader.hidden = true;
}

void start();

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register("sw.js");
}

// Coming back to a page the browser kept in memory must not leave the loader showing.
window.addEventListener("pageshow", () => {
  const loader = document.getElementById("loader");
  if (loader && document.getElementById("app")?.childElementCount) loader.hidden = true;
});
