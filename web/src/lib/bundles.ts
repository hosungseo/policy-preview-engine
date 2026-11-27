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

// Runs saved before the household rename call this group "한부모·자녀". It is the same group (living with children,
// no spouse in the household), renamed so it reads as household composition rather than 한부모가족 eligibility.
const LEGACY_FAMILY: Record<string, string> = { "한부모·자녀": "배우자 없이 자녀와 거주" };

function renameFamily(b: Bundle): Bundle {
  const rename = (label: string) => LEGACY_FAMILY[label] ?? label;
  for (const p of b.personas) p.family = rename(p.family);
  const family = (b.population as { family?: Record<string, number> }).family;
  if (family) (b.population as { family?: Record<string, number> }).family =
    Object.fromEntries(Object.entries(family).map(([k, v]) => [rename(k), v]));
  for (const row of b.analysis.by_group?.family ?? []) row.group = rename(row.group);
  for (const row of b.analysis.jev?.by_group?.family ?? []) row.group = rename(row.group);
  return b;
}

export function getRun(id: string): Bundle {
  for (const dir of DIRS) {
    const file = join(dir, `${id}.json`);
    if (existsSync(file)) return renameFamily(readJson<Bundle>(file));
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
