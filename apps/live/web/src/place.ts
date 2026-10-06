import { el, howSure, plural } from "./dom";
import { CLASS_COLOURS, CLASS_LABELS, type Mark } from "./fire-map";
import { around, CLOSEST_KM, INDIA, type Bounds } from "./projection";
import type { Air, Cell, Feed } from "./schema";
import { CORRIDOR_KM, kmBetween, type Point, upwindSources } from "./upwind";

// Your air: pick a city, or share a location, and the map closes in on it. The card then
// says what the satellites saw around it today, tomorrow's air forecast, and, on the
// evening the wind is carried, which fire cells the air passed over on its way there. A
// shared location is used on this device only and never sent anywhere.

export interface PlaceHooks {
  focus(bounds: Bounds): void;
  setMarks(marks: Mark[]): void;
  setPath(path: Point[] | undefined): void;
  onCity(city: string): void;
}

const CATEGORY_CLASS: Record<string, string> = {
  Good: "air-good",
  Satisfactory: "air-good",
  Moderate: "air-moderate",
  Poor: "air-poor",
  "Very Poor": "air-bad",
  Severe: "air-bad",
};

function inIndia([lon, lat]: Point): boolean {
  return lon >= INDIA.west && lon <= INDIA.east && lat >= INDIA.south && lat <= INDIA.north;
}

export function cellsNear(cells: Cell[], at: Point, km: number): Cell[] {
  return cells.filter((cell) => kmBetween(at, cell.centre) <= km);
}

function classSummary(cells: Cell[]): HTMLElement {
  const list = el("ul", "class-list");
  const counts = new Map<Cell["class"], number>();
  for (const cell of cells) counts.set(cell.class, (counts.get(cell.class) ?? 0) + 1);
  for (const [cls, n] of [...counts.entries()].sort((a, b) => b[1] - a[1])) {
    const item = el("li", "");
    const swatch = el("span", "swatch");
    swatch.style.background = CLASS_COLOURS[cls];
    item.append(swatch, document.createTextNode(`${CLASS_LABELS[cls]}: ${plural(n, "cell")}`));
    list.append(item);
  }
  return list;
}

function airRank(air: Air[], city: string): string | null {
  const known = air.filter((a) => a.pm25_24h_mean !== null).sort((a, b) => (a.pm25_24h_mean ?? 0) - (b.pm25_24h_mean ?? 0));
  const at = known.findIndex((a) => a.city === city);
  if (at < 0 || known.length < 2) return null;
  if (at === 0) return `The cleanest forecast of ${known.length} cities.`;
  if (at === known.length - 1) return `The dirtiest forecast of ${known.length} cities.`;
  return `${ordinal(at + 1)} cleanest of ${known.length} cities.`;
}

function ordinal(n: number): string {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th";
  return `${n}${tail}`;
}

function nearestCity(air: Air[], at: Point): { air: Air; km: number } | null {
  let best: { air: Air; km: number } | null = null;
  for (const a of air) {
    const place: Point | undefined = a.lon !== undefined && a.lat !== undefined ? [a.lon, a.lat] : CITY_POSITIONS[a.city];
    if (!place) continue;
    const km = kmBetween(at, place);
    if (!best || km < best.km) best = { air: a, km };
  }
  return best;
}

// Where each forecast city is, for evenings built before the feed carried positions. A
// test on the Python side keeps this list the same as feed.py AIR_CITIES.
export const CITY_POSITIONS: Record<string, Point> = {
  Delhi: [77.21, 28.61],
  Chandigarh: [76.78, 30.73],
  Ludhiana: [75.86, 30.90],
  Amritsar: [74.87, 31.63],
  Jaipur: [75.79, 26.91],
  Dehradun: [78.03, 30.32],
  Lucknow: [80.95, 26.85],
  Patna: [85.14, 25.59],
  Srinagar: [74.80, 34.08],
  Jammu: [74.86, 32.73],
  Shimla: [77.17, 31.10],
  Kanpur: [80.33, 26.45],
  Varanasi: [82.97, 25.32],
  Ahmedabad: [72.57, 23.02],
  Bhopal: [77.41, 23.26],
  Mumbai: [72.88, 19.08],
  Kolkata: [88.36, 22.57],
  Bhubaneswar: [85.82, 20.30],
  Guwahati: [91.74, 26.14],
  Hyderabad: [78.49, 17.39],
  Bengaluru: [77.59, 12.97],
  Chennai: [80.27, 13.08],
};

const GEO_ERRORS: Record<number, string> = {
  1: "Location is blocked for this site. Allow it in your browser's site settings, or tap the map instead.",
  2: "Your device could not work out where it is. Check that location services are on, or tap the map instead.",
  3: "Finding your location took too long. Try again, or tap the map instead.",
};

function locate(): Promise<Point> {
  return new Promise((resolve, reject) => {
    if (!window.isSecureContext || !("geolocation" in navigator)) {
      reject(new Error("This browser cannot share a location here. Tap the map instead."));
      return;
    }
    const ask = (precise: boolean, retry: boolean): void => {
      navigator.geolocation.getCurrentPosition(
        (position) => resolve([position.coords.longitude, position.coords.latitude]),
        (error) => {
          // A quick network fix fails on some desktops; a second, precise attempt often works.
          if (retry && error.code !== 1) ask(true, false);
          else reject(new Error(GEO_ERRORS[error.code] ?? "Location was not shared. Tap the map instead."));
        },
        { enableHighAccuracy: precise, timeout: precise ? 20_000 : 8_000, maximumAge: 300_000 },
      );
    };
    ask(false, true);
  });
}

export function placeCard(feed: Feed, initialCity: string, hooks: PlaceHooks): { card: HTMLElement; showPoint(at: Point, label: string): void } {
  const air = feed.air ?? [{ city: feed.tomorrow.city, pm25_24h_mean: feed.tomorrow.pm25_24h_mean, cpcb_category: feed.tomorrow.cpcb_category }];
  const card = el("section", "card place");
  card.append(el("h2", "", "Your air"));
  const row = el("div", "place-row");
  const select = el("select", "city-select");
  select.setAttribute("aria-label", "City");
  for (const a of air) {
    const option = el("option", "", a.city);
    option.value = a.city;
    select.append(option);
  }
  const locateButton = el("button", "button", "Use my location");
  locateButton.type = "button";
  row.append(select, locateButton);
  const output = el("div", "place-output");
  card.append(row, output);

  const smokeAt = (at: Point, name: string): HTMLElement[] => {
    if (!feed.wind) {
      hooks.setPath(undefined);
      return [el("p", "muted small", "Wind is carried only for today's evening, so the smoke trace is not available for this day.")];
    }
    const { path, sources } = upwindSources(at, feed.wind, feed.cells);
    hooks.setPath(path);
    if (sources.length === 0) return [el("p", "small", `The air that reached ${name} in the last six hours passed over no fire cells.`)];
    const nearest = Math.min(...sources.map((s) => s.distanceKm));
    return [
      el(
        "p",
        "small",
        `The air that reached ${name} in the last six hours passed within ${CORRIDOR_KM} km of ${plural(sources.length, "fire cell")}, the nearest ${nearest} km away. The dashed line on the map is its path.`,
      ),
      classSummary(sources.map((s) => s.cell)),
      howSure("low", "A back trajectory from forecast winds, not a smoke measurement."),
    ];
  };

  const describe = (at: Point, name: string, forecast: Air | null, note?: string, zoom = true): void => {
    const near = cellsNear(feed.cells, at, CLOSEST_KM);
    const evening = near.filter((c) => c.evening).length;
    const parts: HTMLElement[] = [];
    if (note) parts.push(el("p", "muted small", note));
    if (forecast) {
      const box = el("div", "air-box");
      const category = forecast.cpcb_category;
      box.append(
        el("span", "air-label", `Tomorrow in ${forecast.city}`),
        el("span", "air-value", forecast.pm25_24h_mean === null ? "PM2.5 not measured" : `PM2.5 about ${Math.round(forecast.pm25_24h_mean)} µg/m³`),
        el("span", `air-category ${category ? (CATEGORY_CLASS[category] ?? "") : ""}`, category ? `CPCB: ${category}` : "Category not measured"),
      );
      const rank = airRank(air, forecast.city);
      if (rank) box.append(el("span", "muted small", rank));
      parts.push(box, el("p", "muted small", `${feed.tomorrow.source}. For ${feed.tomorrow.forecast_date}.`));
    }
    parts.push(el("h3", "", `Fires within ${CLOSEST_KM} km today`));
    if (near.length === 0) parts.push(el("p", "small", "None seen today."));
    else {
      parts.push(el("p", "small", `${plural(near.length, "fire cell")}, ${evening} of them burning in the evening.`), classSummary(near));
    }
    parts.push(el("h3", "", "Where the air came from"), ...smokeAt(at, name));
    output.replaceChildren(...parts);
    if (zoom) hooks.focus(around(at));
  };

  const showCity = (city: string, zoom = true): void => {
    const forecast = air.find((a) => a.city === city) ?? null;
    const at: Point | undefined =
      forecast?.lon !== undefined && forecast.lat !== undefined ? [forecast.lon, forecast.lat] : CITY_POSITIONS[city];
    if (!at) {
      output.replaceChildren(el("p", "muted small", "This city's position is not known, so the map cannot close in."));
      hooks.setMarks([]);
      return;
    }
    hooks.setMarks([{ at, label: city }]);
    describe(at, city, forecast, undefined, zoom);
  };

  const showPoint = (at: Point, label: string): void => {
    if (!inIndia(at)) {
      output.replaceChildren(el("p", "small", "That point is outside India, so there is nothing to trace."));
      return;
    }
    const nearest = nearestCity(air, at);
    hooks.setMarks([{ at, label }]);
    describe(at, label === "You" ? "you" : "this point", nearest?.air ?? null, nearest ? `Nearest city with a forecast: ${nearest.air.city}, ${Math.round(nearest.km)} km away.` : undefined);
  };

  select.value = air.some((a) => a.city === initialCity) ? initialCity : (air[0]?.city ?? "");
  select.addEventListener("change", () => {
    hooks.onCity(select.value);
    showCity(select.value);
  });
  locateButton.addEventListener("click", () => {
    locateButton.disabled = true;
    locateButton.textContent = "Finding you...";
    locate()
      .then((at) => showPoint(at, "You"))
      .catch((error: unknown) => output.replaceChildren(el("p", "small", error instanceof Error ? error.message : "Location was not shared. Tap the map instead.")))
      .finally(() => {
        locateButton.disabled = false;
        locateButton.textContent = "Use my location";
      });
  });
  card.append(el("p", "muted small", "Or tap anywhere on the map. Your location stays on this device."));
  showCity(select.value, false);
  return { card, showPoint };
}
