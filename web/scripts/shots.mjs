// Full-page screenshots of every page at desktop and mobile widths (deviceScaleFactor 2),
// plus a horizontal-overflow check. Usage: [SERIES=housing] node scripts/shots.mjs <run-id> [...run-ids]
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { chromium } from "playwright";

const base = process.env.BASE ?? "http://localhost:3200";
const out = process.env.SHOTS ?? "../data/shots";
const ids = process.argv.slice(2);
const paths = ["/", "/explore/", "/new/", "/method/"];
for (const id of ids) {
  for (const sub of ["", "jev/", "text/", "panel/", "hearing/", "plan/", "progress/"]) paths.push(`/runs/${id}/${sub}`);
}
for (const id of (process.env.SERIES ?? "").split(",").filter(Boolean)) {
  paths.push(`/series/${id}/`);
  for (const dir of ["public/series", "dev-series"]) {
    const file = `${dir}/${id}.json`;
    if (existsSync(file)) { paths.push(`/series/${id}/${JSON.parse(readFileSync(file, "utf8")).measures[0].id}/`); break; }
  }
}
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [label, width] of [["desktop", 1440], ["mobile", 400]]) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(`${page.url()} ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error") errors.push(`${page.url()} ${m.text()}`); });
  for (const path of paths) {
    await page.goto(base + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(path.endsWith("progress/") ? 8500 : 400);
    const name = `${label}${path.replaceAll("/", "_")}.png`;
    await page.screenshot({ path: `${out}/${name}`, fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
    console.log(label, path, overflow ? "HORIZONTAL-OVERFLOW" : "ok");
  }
  if (errors.length) console.log("console errors:\n" + errors.join("\n"));
  await context.close();
}
await browser.close();
