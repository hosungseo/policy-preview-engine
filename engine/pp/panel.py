"""Representative (stratified) and affected (targeted, diversified) panels."""
from __future__ import annotations

import random
from collections import defaultdict

from . import config, personas


def allocate(sizes: dict, n: int) -> dict:
    """Largest-remainder allocation of n seats proportional to stratum sizes."""
    total = sum(sizes.values())
    if total == 0 or n <= 0:
        return {k: 0 for k in sizes}
    n = min(n, total)
    quotas = {k: n * v / total for k, v in sizes.items()}
    seats = {k: int(q) for k, q in quotas.items()}
    remaining = n - sum(seats.values())
    order = sorted(sizes, key=lambda k: (-(quotas[k] - seats[k]), str(k)))
    for key in order[:remaining]:
        seats[key] += 1
    return seats


def sample_representative(strata: dict, n: int, seed: int = 42) -> list[int]:
    seats = allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    picked: list[int] = []
    for key in sorted(strata, key=str):
        if seats[key]:
            picked += rng.sample(strata[key], min(seats[key], len(strata[key])))
    return picked


def normalize_spec(raw: dict) -> dict:
    """Validate an LLM targeting spec; unknown keys and provinces are dropped."""
    if not isinstance(raw, dict):
        raise ValueError("spec must be an object")
    filters = []
    for group in raw.get("filters") or []:
        if not isinstance(group, dict):
            continue
        g = {k: v for k, v in group.items() if k in personas.FILTER_KEYS and v not in (None, "", [])}
        for key in ("occupation_like", "family_type_like", "housing_type_in", "education_in", "province_in"):
            if key in g and not isinstance(g[key], list):
                g[key] = [g[key]]
            if key in g:
                g[key] = [str(x) for x in g[key]]
        if "province_in" in g:
            provinces = [config.to_raw_province(p) for p in g["province_in"]]
            g["province_in"] = [p for p in provinces if p]
            if not g["province_in"]:
                del g["province_in"]
        if g:
            filters.append(g)
    keywords = [str(k).strip() for k in (raw.get("keywords") or []) if str(k).strip()][:12]
    query = str(raw.get("semantic_query") or "").strip()
    if not filters and not personas.usable_keywords(keywords) and not query:
        raise ValueError("targeting spec has no usable channel")
    return {
        "filters": filters[:4],
        "keywords": keywords,
        "semantic_query": query,
        "rationale": str(raw.get("rationale") or "").strip(),
    }


def diversify(cands: list[dict], k: int, max_per_occupation: int = 5, seed: int = 42) -> list[dict]:
    """Pick k candidates round-robin over (region, age band), capping each occupation.

    When a policy touches only a few occupations the cap would stop the panel short of k, so the cap
    rises in steps of max_per_occupation until the panel fills. While the first cap still fills the
    panel the picks are the same as with a fixed cap.
    """
    rng = random.Random(seed)
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for cand in cands:
        buckets[(config.REGION_OF[cand["province"]], config.age_band(cand["age"]))].append(cand)
    for items in buckets.values():
        rng.shuffle(items)
        items.sort(key=lambda c: -len(c["found_by"]))
    keys = sorted(buckets, key=str)
    rng.shuffle(keys)
    per_occupation: dict[str, int] = defaultdict(int)
    picked: list[dict] = []
    cap = max_per_occupation
    while len(picked) < k and any(buckets[key] for key in keys):
        progressed = False
        for key in keys:
            if len(picked) >= k:
                break
            items = buckets[key]
            for i, cand in enumerate(items):
                if per_occupation[cand["occupation"]] < cap:
                    per_occupation[cand["occupation"]] += 1
                    picked.append(items.pop(i))
                    progressed = True
                    break
        if not progressed:
            cap += max_per_occupation
    return picked


def interleave(lists: list[list[int]]) -> list[int]:
    """Round-robin merge without duplicates, so every filter group gets its share of a capped channel."""
    out: list[int] = []
    seen: set[int] = set()
    for i in range(max((len(items) for items in lists), default=0)):
        for items in lists:
            if i < len(items) and items[i] not in seen:
                seen.add(items[i])
                out.append(items[i])
    return out


def build_affected(conn, spec: dict, exclude: set[int], k: int = 100,
                   semantic_ids: list[int] | None = None, seed: int = 42) -> tuple[list[dict], dict]:
    """Union of three channels minus the representative panel, then diversified."""
    filter_hits = interleave([personas.filter_ids(conn, group, limit=300, seed=seed) for group in spec["filters"]])
    channels = {
        "filter": filter_hits[:300],
        "fts": personas.fts_ids(conn, spec["keywords"], limit=300),
        "semantic": list(semantic_ids or [])[:300],
    }
    found_by: dict[int, list[str]] = {}
    for name, ids in channels.items():
        for pid in ids:
            if pid in exclude:
                continue
            found_by.setdefault(pid, [])
            if name not in found_by[pid]:
                found_by[pid].append(name)
    rows = personas.fetch(conn, list(found_by))
    cands = [{"id": r["id"], "province": r["province"], "age": r["age"], "occupation": r["occupation"],
              "found_by": found_by[r["id"]]} for r in rows]
    picked = diversify(cands, k, seed=seed)
    return picked, {name: len(ids) for name, ids in channels.items()}
