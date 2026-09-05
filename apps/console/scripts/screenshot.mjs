/**
 * Screenshot the running console at two zoom levels.
 *
 * This exists because four green automated checks once passed on a page showing a
 * blank rectangle: the build succeeded, the typecheck passed, the server returned
 * HTTP 200, and every artifact value appeared in the served HTML. None of them
 * looked at the rendered result. D51.
 *
 * The OSM Foundation tile usage policy prohibits bots that pan and zoom to force
 * tile rendering, which is exactly what this does. It is compliant only because the
 * basemap is now configuration: with NEXT_PUBLIC_BASEMAP_TILES unset no tiles are
 * fetched at all. If you configure a provider, check that provider's terms before
 * running this, because this script is the thing their terms are about. D69.
 *
 * DEPENDENCY: if NEXT_PUBLIC_BASEMAP_TILES is ever set, recheck this script against
 * that provider's terms before running it. The policy question is dormant only
 * because no tiles are fetched while the variable is unset. Configuring a provider
 * reactivates it, and the person configuring one will not be the person who read
 * the policy. D69, D70.
 *
 * Requires the dev server on port 3000 and a Chromium binary. Usage:
 *   npm run dev
 *   npm run shots
 */
import { existsSync } from "node:fs";
import puppeteer from "puppeteer-core";

const CANDIDATES = [
  "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/chromium",
  "/usr/bin/google-chrome",
];

const executablePath = CANDIDATES.find((p) => existsSync(p));
if (!executablePath) {
  console.error("No Chromium binary found. Tried:\n  " + CANDIDATES.join("\n  "));
  process.exit(2);
}

const OUT = "../../docs/figures";
const browser = await puppeteer.launch({
  executablePath,
  headless: "new",
  args: ["--no-sandbox"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1600, height: 1000, deviceScaleFactor: 2 });
await page.goto("http://localhost:3000/", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 12000));

const state = await page.evaluate(() => ({
  mapError: document.querySelector(".maperror")?.textContent?.slice(0, 80) ?? null,
  canvas: (() => {
    const c = document.querySelector(".maplibregl-canvas");
    return c ? [c.clientWidth, c.clientHeight] : null;
  })(),
  sourceRows: document.querySelectorAll(".srrow").length,
  scopeDeclared: document.querySelector(".scrub")?.textContent?.includes("different scopes") ?? false,
}));
console.log("country zoom:", JSON.stringify(state));
if (state.mapError) {
  console.error("map reported an error, not screenshotting a broken page");
  await browser.close();
  process.exit(1);
}
// A null canvas means MapLibre never rendered. This once exited zero and wrote a
// screenshot of an unstyled page with no map, because only mapError was treated as
// fatal and the field that said the map was absent was merely printed. D67.
if (!state.canvas) {
  console.error("no map canvas: the page rendered without MapLibre. Refusing to write a figure.");
  console.error("Usually a stale dev server on port 3000. Check the Local: line in the dev log.");
  await browser.close();
  process.exit(1);
}
if (!state.sourceRows) {
  console.error("the persistent source panel is empty. Refusing to write a figure.");
  await browser.close();
  process.exit(1);
}
await page.screenshot({ path: `${OUT}/console_country.png` });

// Jharkhand, where the largest unregistered persistent sources sit.
await page.evaluate(() => {
  const row = Array.from(document.querySelectorAll(".srrow")).find((r) =>
    r.textContent?.includes("Jharkhand"),
  );
  row?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
});
await new Promise((r) => setTimeout(r, 9000));
await page.screenshot({ path: `${OUT}/console_jharkhand.png` });
console.log("wrote console_country.png and console_jharkhand.png");
await browser.close();
