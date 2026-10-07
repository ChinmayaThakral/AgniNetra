import { previousDay } from "./days";
import { el } from "./dom";
import { Theme } from "./records";
import { recall, remember } from "./store";

export const CONSOLE_URL = "https://agninetra-console.chinmayathakral.com";
export const REPO_URL = "https://github.com/ChinmayaThakral/AgniNetra";
// The scorecard reaches back two evenings and no further; the server refuses older ones.
export const DAYS_BACK = 2;

export function allowedDays(latest: string): string[] {
  const days = [latest];
  for (let i = 0; i < DAYS_BACK; i += 1) days.push(previousDay(days[days.length - 1] ?? latest));
  return days;
}

export function chosenDay(search: string, latest: string): string {
  const asked = new URLSearchParams(search).get("day");
  return asked && allowedDays(latest).includes(asked) ? asked : latest;
}

// Today in India, whatever the visitor's own clock zone, as the feed dates its evenings.
function todayIst(): string {
  return new Date(Date.now() + 5.5 * 3_600_000).toISOString().slice(0, 10);
}

function label(day: string): string {
  const today = todayIst();
  if (day === today) return "Today";
  if (day === previousDay(today)) return "Yesterday";
  const date = new Date(`${day}T00:00:00Z`);
  return date.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
}

export function dayNav(latest: string, chosen: string, available: Set<string>): HTMLElement {
  const nav = el("nav", "day-nav");
  nav.setAttribute("aria-label", "Evening");
  // Before the first build of the day the newest evening is yesterday's. Today still gets
  // its place, greyed, saying when it arrives, rather than silently going missing.
  const today = todayIst();
  if (latest < today) {
    const pending = el("a", "day missing", "Today, from 16:37");
    pending.title = "Today's evening is built from 16:37 IST and refreshed every 30 minutes. Until then the newest is yesterday's.";
    pending.setAttribute("aria-disabled", "true");
    nav.append(pending);
  }
  for (const day of allowedDays(latest)) {
    const link = el("a", day === chosen ? "day current" : "day", label(day));
    if (day === chosen) link.setAttribute("aria-current", "page");
    if (available.has(day)) {
      link.href = day === latest ? "./" : `./?day=${day}`;
      // Netu dances while the other evening loads.
      link.addEventListener("click", () => {
        const loader = document.getElementById("loader");
        if (loader && day !== chosen) loader.hidden = false;
      });
    }
    else {
      link.classList.add("missing");
      link.title = "This evening is not on the server yet; it fills in after the next build.";
      link.setAttribute("aria-disabled", "true");
    }
    nav.append(link);
  }
  return nav;
}

export function currentTheme(): Theme {
  const fallback: Theme = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  return recall("theme", (v) => Theme.parse(v), fallback);
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "light" ? "#f4f1ea" : "#07090d");
}

export function themeButton(): HTMLButtonElement {
  const button = el("button", "icon-button");
  const paint = (): void => {
    const theme = currentTheme();
    button.textContent = theme === "light" ? "Dark" : "Light";
    button.setAttribute("aria-label", `Switch to the ${theme === "light" ? "dark" : "light"} theme`);
  };
  button.addEventListener("click", () => {
    const next: Theme = currentTheme() === "light" ? "dark" : "light";
    remember("theme", next);
    applyTheme(next);
    paint();
    window.dispatchEvent(new Event("resize"));
  });
  paint();
  return button;
}

export function siteLinks(): HTMLElement {
  const nav = el("nav", "site-links");
  const links: [string, string][] = [
    ["Research console", CONSOLE_URL],
    ["Privacy", "privacy.html"],
    ["Code", REPO_URL],
  ];
  for (const [text, href] of links) {
    const link = el("a", "", text);
    link.href = href;
    if (href.startsWith("http")) link.rel = "noopener";
    nav.append(link);
  }
  return nav;
}

export function tabs(panels: [string, HTMLElement][], key: string): HTMLElement {
  const box = el("section", "tabs");
  const bar = el("div", "tab-bar");
  bar.setAttribute("role", "tablist");
  const saved = recall(key, (v) => String(v), panels[0]?.[0] ?? "");
  const show = (name: string): void => {
    for (const [title, panel] of panels) {
      panel.hidden = title !== name;
      bar.querySelector(`[data-tab="${title}"]`)?.setAttribute("aria-selected", String(title === name));
    }
  };
  for (const [title] of panels) {
    const button = el("button", "tab", title);
    button.dataset.tab = title;
    button.setAttribute("role", "tab");
    button.addEventListener("click", () => {
      remember(key, title);
      show(title);
    });
    bar.append(button);
  }
  box.append(bar, ...panels.map(([, panel]) => panel));
  show(panels.some(([title]) => title === saved) ? saved : (panels[0]?.[0] ?? ""));
  return box;
}
