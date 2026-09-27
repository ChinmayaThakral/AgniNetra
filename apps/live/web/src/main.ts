import "./style.css";
import { el, howSure } from "./dom";
import { CLASS_COLOURS, CLASS_LABELS, drawFireMap } from "./fire-map";
import { heatleCard } from "./heatle";
import { matchBoard } from "./match-board";
import { moodOf, netuSvg } from "./netu";
import { fit, INDIA, NORTH_INDIA, type Bounds } from "./projection";
import { Boundaries, Feed } from "./schema";
import { matchShareCard, shareCanvas } from "./share-card";
import { tomorrowCard } from "./tomorrow-card";

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

  const header = el("header", "top");
  header.append(netuSvg(moodOf(feed)));
  const lines = el("div", "netu-lines");
  for (const line of feed.netu) lines.append(el("p", "netu-line", line.text));
  header.append(lines);

  const mapCard = el("section", "card map-card");
  const canvas = el("canvas", "fire-map");
  const controls = el("div", "map-controls");
  let bounds: Bounds = NORTH_INDIA;
  let eveningOnly = false;
  let ring: [number, number] | null = null;
  const redraw = (): void => {
    drawFireMap(canvas, boundaries, feed.cells, { bounds, untilEvening: eveningOnly });
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
  const legend = el("ul", "legend");
  for (const key of Object.keys(CLASS_LABELS) as (keyof typeof CLASS_LABELS)[]) {
    const item = el("li", "");
    const swatch = el("span", "swatch");
    swatch.style.background = CLASS_COLOURS[key];
    item.append(swatch, document.createTextNode(CLASS_LABELS[key]));
    legend.append(item);
  }
  mapCard.append(canvas, controls, legend, howSure("low"));

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
    matchBoard(feed),
    mapCard,
    share,
    tomorrowCard(feed),
    heatleCard(feed, (centre) => {
      ring = centre;
      bounds = INDIA;
      redraw();
    }),
    footer,
  );
  redraw();
  window.addEventListener("resize", redraw);
}

void start();

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register("sw.js");
}
