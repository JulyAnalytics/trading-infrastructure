// Capture workstation screenshots for docs/wiki/images/.
// Requires: frontend dev server (:5173) + API (:8100) running, and
// `npm i -D playwright` + `npx playwright install chromium` in frontend/.
// Run:  node scripts/capture_wiki_screenshots.mjs   (from repo root)
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
import { mkdirSync } from "node:fs";

const OUT = new URL("../docs/wiki/images/", import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

const BASE = "http://localhost:5173";
const VIEWPORT = { width: 1600, height: 1100 };

// [file, route, optional tab-button text to click first, settle ms]
const SHOTS = [
  ["command-deck.png", "/", null, 6000],
  ["marcus-workspace.png", "/marcus", null, 8000],
  ["sarah-vol-monitor.png", "/sarah", null, 9000],
  ["sarah-greeks-scenarios.png", "/sarah", "Greeks & scenarios", 3000],
  ["sarah-memo-builder.png", "/sarah", "Pre-trade memo", 3000],
  ["sarah-regime-library.png", "/sarah", "Regime library", 8000],
  ["priya-workbench.png", "/priya", null, 6000],
  ["jordan-risk.png", "/jordan", null, 8000],
  ["params-page.png", "/params", null, 5000],
  ["jobs-health.png", "/jobs", null, 5000],
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: VIEWPORT });

for (const [file, route, tab, settle] of SHOTS) {
  try {
    if (page.url() !== BASE + route) {
      await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 30000 })
        .catch(() => {}); // plotly keeps sockets busy; fall through to settle wait
    }
    if (tab) {
      await page.getByRole("button", { name: tab }).first().click({ timeout: 10000 });
    }
    await page.waitForTimeout(settle);
    await page.screenshot({ path: OUT + file, fullPage: false });
    console.log("captured", file);
  } catch (e) {
    console.error("FAILED", file, String(e).slice(0, 120));
  }
}

await browser.close();
