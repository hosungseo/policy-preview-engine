// Series bundles are read at build time. Mock bundles (dev-series) are read only in `next dev`, or when
// PP_INCLUDE_DEV_RUNS=1 is set for a local check build. Never set it for deploy builds.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { SeriesBundle } from "./seriesTypes";

const ROOT = process.cwd();
const includeDev = process.env.NODE_ENV !== "production" || process.env.PP_INCLUDE_DEV_RUNS === "1";

export function getSeries(id: string): SeriesBundle | null {
  const dirs = [join(ROOT, "public", "series"), ...(includeDev ? [join(ROOT, "dev-series")] : [])];
  for (const dir of dirs) {
    const file = join(dir, `${id}.json`);
    if (existsSync(file)) return { ...(JSON.parse(readFileSync(file, "utf8")) as SeriesBundle), dev: dir.endsWith("dev-series") };
  }
  return null;
}
