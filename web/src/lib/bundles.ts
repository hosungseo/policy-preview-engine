// Server-side bundle loading at build time. Mock bundles (dev-runs) are only read in `next dev`,
// or when PP_INCLUDE_DEV_RUNS=1 is set for a local check build. Never set it for deploy builds.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { Bundle, Persona, Reaction, RunSummary, Segment } from "./types";

const ROOT = process.cwd();
const includeDev = process.env.NODE_ENV !== "production" || process.env.PP_INCLUDE_DEV_RUNS === "1";
const DIRS = [join(ROOT, "public", "runs"), ...(includeDev ? [join(ROOT, "dev-runs")] : [])];

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export function listRuns(): RunSummary[] {
  const seen = new Map<string, RunSummary>();
  for (const dir of DIRS) {
    const index = join(dir, "index.json");
    if (!existsSync(index)) continue;
    for (const entry of readJson<RunSummary[]>(index)) {
      if (!seen.has(entry.id)) seen.set(entry.id, { ...entry, dev: dir.endsWith("dev-runs") });
    }
  }
  return [...seen.values()].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getRun(id: string): Bundle {
  for (const dir of DIRS) {
    const file = join(dir, `${id}.json`);
    if (existsSync(file)) return readJson<Bundle>(file);
  }
  throw new Error(`bundle not found: ${id}`);
}

export function runParams(): { id: string }[] {
  return listRuns().map((r) => ({ id: r.id }));
}

export interface BundleIndex {
  person: Map<string, Persona>;
  reactionByRid: Map<string, Reaction>;
  reactionByUuid: Map<string, Reaction>;
  segment: Map<string, Segment>;
}

export function indexBundle(b: Bundle): BundleIndex {
  return {
    person: new Map(b.personas.map((p) => [p.uuid, p])),
    reactionByRid: new Map(b.reactions.map((r) => [r.rid, r])),
    reactionByUuid: new Map(b.reactions.map((r) => [r.uuid, r])),
    segment: new Map(b.segments.map((s) => [s.id, s])),
  };
}
