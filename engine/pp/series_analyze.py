"""Aggregates for a Jev-only policy series. Every number is an average of Jev's calibrated probabilities over a
fixed panel; groups smaller than SMALL_N are marked `small` and not interpreted."""
from __future__ import annotations

import math
from collections import defaultdict

from . import config, regulated
from .housing_context import PRICE_BAND_ORDER
from .series_questions import HOUSING, TENURE

SMALL_N = 100
GROUPINGS = {
    "province": lambda p: config.PROVINCE_DISPLAY[p["province"]],
    "region": lambda p: config.REGION_OF[p["province"]],
    "age_band": lambda p: config.age_band(int(p["age"])),
    "sex": lambda p: p["sex"],
    "housing_type": lambda p: p["housing_type"],
}
ORDER = {
    "province": list(config.PROVINCE_DISPLAY.values()),
    "region": list(config.REGIONS),
    "age_band": [band[2] for band in config.AGE_BANDS],
    "sex": ["남자", "여자"],
    "housing_type": list(config.HOUSING_ORDER),
    "tenure": [label for label, _ in TENURE.values()],
    "regulated": list(regulated.LABELS),
    "price_band": PRICE_BAND_ORDER,
}
KIND_LABEL = {"province": "시도", "region": "권역", "age_band": "연령대", "sex": "성별", "housing_type": "주택 종류",
              "tenure": "점유 형태(추정)", "regulated": "발표일 규제지역", "price_band": "사는 곳 아파트값"}
HOUSING_KINDS = ("region", "age_band", "regulated")
# Groupings a run adds to each person itself (housing runs: the district's price band).
OPTIONAL = ("price_band",)


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 4) if xs else 0.0


def ci95(xs: list[float]) -> list[float] | None:
    """Normal-approximation 95% interval of a mean (the panel is large)."""
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    half = 1.96 * math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) / math.sqrt(n)
    return [round(m - half, 4), round(m + half, 4)]


def _weighted(values: list[float], weights: list[float]) -> float:
    total = sum(weights)
    return round(sum(v * w for v, w in zip(values, weights)) / total, 4) if total else 0.0


def _stats(rows: list[dict]) -> dict:
    return {"n": len(rows), "favor": _mean([r["favor"] for r in rows]),
            "reserve": _mean([r["reserve"] for r in rows]), "mean": _mean([r["stance"] for r in rows])}


def _grouped(items: list, uuid_of, people: dict, regulated_of: dict) -> dict[str, dict[str, list]]:
    out = {kind: defaultdict(list) for kind in [*GROUPINGS, "regulated"]}
    for item in items:
        u = uuid_of(item)
        for kind, label_of in GROUPINGS.items():
            out[kind][label_of(people[u])].append(item)
        out["regulated"][regulated_of[u]].append(item)
        for kind in OPTIONAL:
            if kind in people[u]:
                out.setdefault(kind, defaultdict(list))[people[u][kind]].append(item)
    return out


def condition_stats(rows: list[dict], people: dict, segments: list[dict], regulated_of: dict) -> dict:
    out = {**_stats(rows), "favor_ci95": ci95([r["favor"] for r in rows]),
           "mass": [_mean([r["stance_probs"][i] for r in rows]) for i in range(5)], "groups": {}, "housing_groups": {}}
    grouped = _grouped(rows, lambda r: r["uuid"], people, regulated_of)
    for kind, acc in grouped.items():
        out["groups"][kind] = [{"group": g, **_stats(acc[g]), "small": len(acc[g]) < SMALL_N}
                               for g in ORDER[kind] if acc.get(g)]
    for kind in HOUSING_KINDS:
        acc = grouped[kind]
        out["housing_groups"][kind] = [
            {"group": g, "n": len(acc[g]), "small": len(acc[g]) < SMALL_N,
             "values": {k: _mean([r["housing"][k] for r in acc[g]]) for k in HOUSING}}
            for g in ORDER[kind] if acc.get(g)]
    tenure, tenure_housing = [], []
    for key, (label, _) in TENURE.items():
        w = [people[r["uuid"]]["tenure"][key] for r in rows]
        n = round(sum(w))
        tenure.append({"group": label, "n": n, "favor": _weighted([r["favor"] for r in rows], w),
                       "reserve": _weighted([r["reserve"] for r in rows], w),
                       "mean": _weighted([r["stance"] for r in rows], w), "small": n < SMALL_N})
        tenure_housing.append({"group": label, "n": n, "small": n < SMALL_N,
                               "values": {k: _weighted([r["housing"][k] for r in rows], w) for k in HOUSING}})
    out["groups"]["tenure"] = tenure
    out["housing_groups"]["tenure"] = tenure_housing
    out["positions"] = {}
    for s in segments:
        mean = _mean([r["positions"][s["id"]] for r in rows])
        oppose = _mean([r["pos_oppose"][s["id"]] for r in rows])
        out["positions"][s["id"]] = {"mean": mean, "oppose": oppose, "support": round(mean + oppose, 4)}
    out["housing"] = {k: _mean([r["housing"][k] for r in rows]) for k in HOUSING}
    return out


def paired_effect(alone: list[dict], context: list[dict], people: dict, regulated_of: dict) -> dict:
    """Per-person change in the probability of favouring, with the earlier measures shown minus without."""
    first = {r["uuid"]: r for r in alone}
    diffs = {c["uuid"]: round(c["favor"] - first[c["uuid"]]["favor"], 4) for c in context if c["uuid"] in first}
    values = list(diffs.values())
    out = {"overall": {"n": len(values), "diff": _mean(values), "ci95": ci95(values)}, "groups": {}}
    grouped = _grouped(list(diffs), lambda u: u, people, regulated_of)
    for kind, acc in grouped.items():
        out["groups"][kind] = [{"group": g, "n": len(acc[g]), "diff": _mean([diffs[u] for u in acc[g]]),
                                "small": len(acc[g]) < SMALL_N} for g in ORDER[kind] if acc.get(g)]
    out["groups"]["tenure"] = []
    for key, (label, _) in TENURE.items():
        w = [people[u]["tenure"][key] for u in diffs]
        n = round(sum(w))
        out["groups"]["tenure"].append({"group": label, "n": n, "diff": _weighted(values, w), "small": n < SMALL_N})
    return out


def _oppose(row: dict) -> float:
    return row["stance_probs"][0] + row["stance_probs"][1]


def before_after(before: dict[str, dict], after: list[dict], people: dict, kinds: tuple[str, ...]) -> dict:
    """The same people answering without (before) and with (after) a change to what they were shown: the shares
    leaning in favour and against, as [before, after], overall and by group. `people[u][kind]` names each group."""
    pairs = [(before[r["uuid"]], r) for r in after if r["uuid"] in before]

    def pair_stats(ps: list[tuple[dict, dict]]) -> dict:
        return {"n": len(ps), "favor": [_mean([b["favor"] for b, _ in ps]), _mean([a["favor"] for _, a in ps])],
                "oppose": [_mean([_oppose(b) for b, _ in ps]), _mean([_oppose(a) for _, a in ps])]}

    out = {"overall": pair_stats(pairs), "groups": {}}
    for kind in kinds:
        acc = defaultdict(list)
        for b, a in pairs:
            acc[people[a["uuid"]][kind]].append((b, a))
        out["groups"][kind] = [{"group": g, **pair_stats(acc[g]), "small": len(acc[g]) < SMALL_N}
                               for g in ORDER[kind] if acc.get(g)]
    return out


def tenure_overall(people: dict) -> dict:
    return {key: _mean([p["tenure"][key] for p in people.values()]) for key in TENURE}


def tenure_by_province(people: dict, official: dict) -> list[dict]:
    acc = defaultdict(list)
    for p in people.values():
        acc[config.PROVINCE_DISPLAY[p["province"]]].append(p["tenure"]["own"])
    return [{"province": prov, "n": len(acc[prov]), "own": _mean(acc[prov]), "official_own": official["own"].get(prov)}
            for prov in ORDER["province"] if acc.get(prov)]


def top_reserve(stats: dict) -> dict | None:
    """The group (of any kind, not small) least inclined to favour the measure."""
    best = None
    for kind, groups in stats["groups"].items():
        for g in groups:
            if not g["small"] and (best is None or g["reserve"] > best["reserve"]):
                best = {"kind": kind, "group": g["group"], "reserve": g["reserve"]}
    return best
