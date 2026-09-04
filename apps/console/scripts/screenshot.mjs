/**
 * Screenshot the running console at two zoom levels.
 *
 * This exists because four green automated checks once passed on a page showing a
 * blank rectangle: the build succeeded, the typecheck passed, the server returned
 * HTTP 200, and every artifact value appeared in the served HTML. None of them
 * looked at the rendered result. D51.
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
