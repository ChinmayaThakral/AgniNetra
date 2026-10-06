import { el, howSure } from "./dom";
import { CLASS_COLOURS, CLASS_LABELS, drawFireMap, type Mark, type TimeFilter } from "./fire-map";
import { type Bounds, fit, NORTH_INDIA, REGIONS } from "./projection";
import type { Boundaries, Cell } from "./schema";
import type { Point } from "./upwind";

// The fire map and every control that changes it, inside the map itself: which part of
// India, which hours, and the Fire Clock, so nothing about the map sits below it.

export interface MapView {
  card: HTMLElement;
  focus(bounds: Bounds, region?: string): void;
  setMarks(marks: Mark[]): void;
  setPath(path: Point[] | undefined): void;
  redraw(): void;
}

const TIMES: [TimeFilter, string, string][] = [
  ["all", "All day", "Every fire cell seen from 10:00 to 20:00 IST"],
  ["day", "Daytime", "Cells seen burning only before 16:00 IST, while the polar satellites still pass"],
  ["evening", "Evening", "Cells seen burning from 16:00 IST, after the last polar pass"],
];

const PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 5v14l12-7z" fill="currentColor"/></svg>';
const STOP_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="1" fill="currentColor"/></svg>';

function clockSlots(): string[] {
  const slots: string[] = [];
  for (let h = 10; h < 20; h += 1) {
    const hh = String(h).padStart(2, "0");
    slots.push(`${hh}:00`, `${hh}:30`);
  }
  return slots;
}

function segmented(label: string, options: [string, string, string?][], chosen: string, pick: (value: string) => void): { box: HTMLElement; set(value: string | null): void } {
  const box = el("div", "segmented");
  box.setAttribute("role", "group");
  box.setAttribute("aria-label", label);
  const buttons = options.map(([value, text, title]) => {
    const button = el("button", "seg", text);
    button.type = "button";
    if (title) button.title = title;
    button.addEventListener("click", () => {
      set(value);
      pick(value);
    });
    box.append(button);
    return [value, button] as const;
  });
  const set = (value: string | null): void => {
    for (const [v, button] of buttons) button.setAttribute("aria-pressed", String(v === value));
  };
  set(chosen);
  return { box, set };
}

export function mapView(boundaries: Boundaries, cells: Cell[], onTap: (point: Point) => void): MapView {
  const card = el("section", "card map-card");
  const frame = el("div", "map-frame");
  const canvas = el("canvas", "fire-map");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", "Map of today's fire cells over India, each an 11 km square, coloured by their likely source. Tap a place to trace where its smoke came from.");

  let bounds: Bounds = NORTH_INDIA;
  let time: TimeFilter = "all";
  let clock: string | undefined;
  let marks: Mark[] = [];
  let path: Point[] | undefined;
  let timer: number | undefined;

  const redraw = (): void => drawFireMap(canvas, boundaries, cells, { bounds, time, clock, path, marks });

  const regions = segmented(
    "Part of India",
    REGIONS.map(([name]) => [name, name] as [string, string]),
    "North",
    (name) => {
      const found = REGIONS.find(([n]) => n === name);
      if (found) bounds = found[1];
      redraw();
    },
  );
  const times = segmented("Hours shown", TIMES.map(([v, t, title]) => [v, t, title]), "all", (value) => {
    time = value as TimeFilter;
    redraw();
  });

  const clockLabel = el("span", "clock-label", "");
  const play = el("button", "map-play");
  play.type = "button";
  const paintPlay = (): void => {
    play.innerHTML = timer === undefined ? PLAY_ICON : STOP_ICON;
    play.append(document.createTextNode(timer === undefined ? " Fire Clock" : " Stop"));
    play.setAttribute("aria-label", timer === undefined ? "Play the Fire Clock: watch the day's fire cells appear half hour by half hour" : "Stop the Fire Clock");
  };
  const stop = (): void => {
    if (timer !== undefined) window.clearTimeout(timer);
    timer = undefined;
    clock = undefined;
    clockLabel.textContent = "";
    paintPlay();
    redraw();
  };
  play.addEventListener("click", () => {
    if (timer !== undefined) {
      stop();
      return;
    }
    const slots = clockSlots();
    let i = 0;
    const tick = (): void => {
      clock = slots[i];
      clockLabel.textContent = clock ? `${clock} IST` : "";
      redraw();
      i += 1;
      timer = i < slots.length ? window.setTimeout(tick, 380) : window.setTimeout(stop, 1200);
    };
    tick();
    paintPlay();
  });
  paintPlay();

  const legend = el("ul", "map-legend");
  for (const key of Object.keys(CLASS_LABELS) as (keyof typeof CLASS_LABELS)[]) {
    const item = el("li", "");
    const swatch = el("span", "swatch");
    swatch.style.background = CLASS_COLOURS[key];
    item.append(swatch, document.createTextNode(CLASS_LABELS[key]));
    legend.append(item);
  }

  const top = el("div", "map-top");
  top.append(regions.box, times.box);
  const bottom = el("div", "map-bottom");
  const clockBox = el("div", "map-clock");
  clockBox.append(play, clockLabel);
  bottom.append(clockBox, legend);
  frame.append(canvas, top, bottom);
  card.append(frame, howSure("low", "Each square is an 11 km cell. Classes are weak labels from maps, not checked on the ground. Not an official count."));

  canvas.addEventListener("click", (event) => {
    const box = canvas.getBoundingClientRect();
    const projection = fit(bounds, canvas.clientWidth, canvas.clientHeight);
    onTap(projection.invert(event.clientX - box.left, event.clientY - box.top));
  });
  window.addEventListener("resize", redraw);

  return {
    card,
    focus(next, region) {
      bounds = next;
      regions.set(region ?? null);
      redraw();
    },
    setMarks(next) {
      marks = next;
      redraw();
    },
    setPath(next) {
      path = next;
      redraw();
    },
    redraw,
  };
}
