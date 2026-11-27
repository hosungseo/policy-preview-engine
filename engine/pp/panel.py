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
    """Normalize aliases, but never silently remove a requested targeting condition."""
    if not isinstance(raw, dict):
        raise ValueError("spec must be an object")
    unknown = set(raw) - {"filters", "keywords", "semantic_query", "rationale"}
    if unknown:
        raise ValueError(f"unknown targeting keys: {sorted(unknown)}")
    groups = raw.get("filters", [])
    if not isinstance(groups, list) or len(groups) > 4:
        raise ValueError("filters must be a list of at most four groups")
    filters = [personas.normalize_filter(group) for group in groups]
    if not isinstance(raw.get("keywords", []), list):
        raise ValueError("keywords must be a list")
    keywords = [str(k).strip() for k in (raw.get("keywords") or []) if str(k).strip()][:12]
    query = str(raw.get("semantic_query") or "").strip()
    if not filters and not personas.usable_keywords(keywords) and not query:
        raise ValueError("targeting spec has no usable channel")
    return {
        "filters": filters,
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
                   semantic_ids: list[int] | None = None, seed: int = 42, *,
                   receipt: dict | None = None) -> tuple[list[dict], dict]:
    """Union of three channels minus the representative panel, then diversified."""
    spec = normalize_spec(spec)
    filter_receipts, lists = [], []
    for group in spec["filters"]:
        audit = {}
        lists.append(personas.filter_ids(conn, group, limit=300, seed=seed, receipt=audit))
        filter_receipts.append(audit)
    filter_hits = interleave(lists)
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
    if receipt is not None:
        receipt.update({"filter_groups": filter_receipts, "filter_merge": "round_robin_deduplicated_limit_300",
                        "fts": {"requested_keywords": spec["keywords"],
                                "usable_keywords": personas.usable_keywords(spec["keywords"]),
                                "order": "bm25 ASC, rowid ASC", "limit": 300},
                        "candidate_count": len(cands), "requested_count": k, "selected_count": len(picked),
                        "excluded_representative_count": len(set().union(*map(set, channels.values())) & exclude),
                        "selection": "region_age_round_robin_then_channel_count_desc_with_seeded_ties",
                        "occupation_cap": 5, "occupation_cap_increment": 5, "seed": seed,
                        "status": "candidate_not_eligibility"})
    return picked, {name: len(ids) for name, ids in channels.items()}
