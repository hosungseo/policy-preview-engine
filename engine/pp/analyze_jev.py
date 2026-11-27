"""Aggregates over the Jev quantitative panel. No generation: every number comes from Jev's
calibrated probabilities, averaged here in code."""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from . import analyze_stats, config
from .jev_panel import CHANNELS, METHODS

SMALL_N = 30  # the Jev panel is large, so hold groups to a stricter minimum than the LLM panel
CLAUSE_KEYS = ("age_band", "region", "occupation_major")
KIND_LABEL = {"age_band": "연령대", "region": "권역", "occupation_major": "직업군"}


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def overall(rows: list[dict], seed: int = 11, boots: int = 1000) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0, "mean": None, "ci95": None, "mass": [0.0] * 5}
    values = [r["stance"] for r in rows]
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(boots))
    mass = [_mean([r["stance_probs"][i] for r in rows]) for i in range(5)]
    return {"n": n, "mean": _mean(values), "ci95": [round(means[int(0.025 * boots)], 4), round(means[int(0.975 * boots) - 1], 4)],
            "mass": mass}


def by_group(rows: list[dict], people: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for key, label_of in analyze_stats.GROUPINGS.items():
        acc: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            acc[label_of(people[r["uuid"]])].append(r)
        groups = []
        order = analyze_stats.ORDER[key]
        for group in order + sorted(set(acc) - set(order)):
            members = acc.get(group)
            if not members:
                continue
            groups.append({"group": group, "n": len(members), "mean": _mean([m["stance"] for m in members]),
                           "reserve": _mean([m["reserve"] for m in members]), "direct": _mean([m["direct"] for m in members]),
                           "comment": _mean([m["comment"] for m in members]), "small": len(members) < SMALL_N})
        out[key] = groups
    return out


def clause_matrix(rows: list[dict], people: dict[str, dict], segments: list[dict]) -> dict:
    ids = [s["id"] for s in segments]
    result = {"overall": {sid: _mean([r["segments"][sid] for r in rows]) for sid in ids}, "groups": {}}
    for key in CLAUSE_KEYS:
        label_of = analyze_stats.GROUPINGS[key]
        acc: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            acc[label_of(people[r["uuid"]])].append(r)
        order = analyze_stats.ORDER[key]
        result["groups"][key] = [
            {"group": g, "n": len(acc[g]), "small": len(acc[g]) < SMALL_N,
             "values": {sid: _mean([r["segments"][sid] for r in acc[g]]) for sid in ids}}
            for g in order + sorted(set(acc) - set(order)) if acc.get(g)
        ]
    return result


def channels(rows: list[dict]) -> list[dict]:
    counts = Counter(r["channel"] for r in rows)
    n = len(rows) or 1
    return [{"key": k, "label": CHANNELS.get(k, k), "n": c, "share": round(c / n, 4)} for k, c in counts.most_common()]


def _grouped(rows: list[dict], people: dict[str, dict], key: str) -> list[tuple[str, list[dict]]]:
    label_of = analyze_stats.GROUPINGS[key]
    acc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        acc[label_of(people[r["uuid"]])].append(r)
    order = analyze_stats.ORDER[key]
    return [(g, acc[g]) for g in order + sorted(set(acc) - set(order)) if acc.get(g)]


def position_matrix(rows: list[dict], people: dict[str, dict], segments: list[dict]) -> dict | None:
    """Clause x group stance: expected position (-1 oppose .. +1 support) and probability of opposing.
    P(support) = E + P(oppose) because the three levels are -1, 0, +1."""
    rows = [r for r in rows if "positions" in r]
    if not rows:
        return None
    ids = [s["id"] for s in segments]
    overall = {}
    for sid in ids:
        mean = _mean([r["positions"][sid] for r in rows])
        oppose = _mean([r["pos_oppose"][sid] for r in rows])
        overall[sid] = {"mean": mean, "oppose": oppose, "support": round(mean + oppose, 4)}
    groups = {key: [{"group": g, "n": len(ms), "small": len(ms) < SMALL_N,
                     "values": {sid: _mean([m["positions"][sid] for m in ms]) for sid in ids},
                     "oppose": {sid: _mean([m["pos_oppose"][sid] for m in ms]) for sid in ids}}
                    for g, ms in _grouped(rows, people, key)] for key in CLAUSE_KEYS}
    return {"overall": overall, "groups": groups}


def issue_prevalence(rows: list[dict], people: dict[str, dict], issues: list[dict], min_lift: float = 1.15) -> dict | None:
    """How likely people in the representative panel are to raise each issue (issue ids from the analysis,
    `k` = the issue's position in the Jev question set), overall and by group, plus the groups that lead it."""
    rows = [r for r in rows if "issues" in r]
    if not rows or not issues:
        return None
    overall = {it["id"]: _mean([r["issues"][str(it["k"])] for r in rows]) for it in issues}
    groups: dict[str, list[dict]] = {}
    leaders: dict[str, list[dict]] = {it["id"]: [] for it in issues}
    for key in CLAUSE_KEYS:
        groups[key] = []
        for g, ms in _grouped(rows, people, key):
            values = {it["id"]: _mean([m["issues"][str(it["k"])] for m in ms]) for it in issues}
            groups[key].append({"group": g, "n": len(ms), "small": len(ms) < SMALL_N, "values": values})
            if len(ms) < SMALL_N:
                continue
            for it in issues:
                base = overall[it["id"]]
                lift = round(values[it["id"]] / base, 2) if base else 0.0
                if lift >= min_lift:
                    leaders[it["id"]].append({"kind": KIND_LABEL[key], "group": g, "n": len(ms),
                                              "mean": values[it["id"]], "lift": lift})
    for it_id in leaders:
        leaders[it_id] = sorted(leaders[it_id], key=lambda x: (-x["lift"], -x["n"], x["group"]))[:4]
    return {"overall": overall, "groups": groups, "leaders": leaders}


def _methods_of(members: list[dict]) -> list[dict]:
    out = [{"key": k, "label": label, "p": _mean([m["methods"][k] for m in members if k in m["methods"]])}
           for k, (label, _) in METHODS.items()]
    return sorted(out, key=lambda x: (-x["p"], x["key"]))


def methods_overall(rows: list[dict]) -> list[dict] | None:
    rows = [r for r in rows if "methods" in r]
    return _methods_of(rows) if rows else None


def methods_matrix(rows: list[dict], people: dict[str, dict]) -> dict | None:
    rows = [r for r in rows if "methods" in r]
    if not rows:
        return None
    return {key: [{"group": g, "n": len(ms), "small": len(ms) < SMALL_N,
                   "values": {k: _mean([m["methods"][k] for m in ms]) for k in METHODS}}
                  for g, ms in _grouped(rows, people, key)] for key in ("age_band", "occupation_major")}


def explain_summary(rows: list[dict], people: dict[str, dict], segments: list[dict]) -> dict | None:
    rows = [r for r in rows if "explain" in r]
    if not rows:
        return None
    ids = [s["id"] for s in segments]
    overall = {sid: _mean([r["explain"].get(sid, 0.0) for r in rows]) for sid in ids}
    understand = {"overall": _mean([r["understand"] for r in rows if "understand" in r])}
    for key in ("education_level", "age_band"):
        understand[key] = [{"group": g, "n": len(ms), "small": len(ms) < SMALL_N,
                            "mean": _mean([m["understand"] for m in ms if "understand" in m])}
                           for g, ms in _grouped(rows, people, key)]
    return {"overall": overall, "top": max(ids, key=lambda sid: overall[sid]) if ids else None, "understand": understand}


def provinces(rows: list[dict], people: dict[str, dict]) -> list[dict]:
    acc: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        acc[people[r["uuid"]]["province"]].append(r)
    return [{"province": config.PROVINCE_DISPLAY.get(raw, raw), "n": len(ms), "mean": _mean([m["stance"] for m in ms]),
             "reserve": _mean([m["reserve"] for m in ms]), "direct": _mean([m["direct"] for m in ms])}
            for raw, ms in sorted(acc.items())]


def _stance_stats(rows: list[dict]) -> dict:
    return {"favor": _mean([r["probs"][3] + r["probs"][4] for r in rows]),
            "reserve": _mean([r["probs"][0] + r["probs"][1] + r["probs"][2] for r in rows]),
            "mean": _mean([r["stance"] for r in rows])}


def _paired_groups(pairs: list[tuple[dict, dict]], people: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for key in CLAUSE_KEYS:
        label_of = analyze_stats.GROUPINGS[key]
        acc: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
        for b, a in pairs:
            acc[label_of(people[b["uuid"]])].append((b, a))
        order = analyze_stats.ORDER[key]
        out[key] = []
        for g in order + sorted(set(acc) - set(order)):
            if not acc.get(g):
                continue
            gb, ga = _stance_stats([b for b, _ in acc[g]]), _stance_stats([a for _, a in acc[g]])
            out[key].append({"group": g, "n": len(acc[g]), "small": len(acc[g]) < SMALL_N,
                             **{f"d_{k}": round(ga[k] - gb[k], 4) for k in ga}})
    return out


def alternatives_summary(rows: list[dict], people: dict[str, dict], drafts: list[dict],
                         placebo_id: str | None = None) -> dict:
    """Paired amendment test: every change is computed on the same people (original vs amended text).
    With a placebo (a sentence that changes nothing), each change is also given net of what merely
    appending text does."""
    by_person: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in rows:
        by_person[r["uuid"]][r["variant"]] = r

    def pairs_for(vid: str) -> list[tuple[dict, dict]]:
        return [(v["base"], v[vid]) for u, v in by_person.items() if "base" in v and vid in v and u in people]

    base_rows = [v["base"] for u, v in by_person.items() if "base" in v and u in people]
    placebo, placebo_groups = None, {}
    if placebo_id:
        pp = pairs_for(placebo_id)
        if pp:
            before, after = _stance_stats([b for b, _ in pp]), _stance_stats([a for _, a in pp])
            placebo = {"n": len(pp), **{f"d_{k}": round(after[k] - before[k], 4) for k in after}}
            placebo_groups = {(key, c["group"]): c for key, cells in _paired_groups(pp, people).items() for c in cells}
    items = []
    for d in drafts:
        pairs = pairs_for(d["id"])
        before, after = _stance_stats([b for b, _ in pairs]), _stance_stats([a for _, a in pairs])
        item = {**d, "n": len(pairs), **after, **{f"d_{k}": round(after[k] - before[k], 4) for k in after}}
        if placebo:
            item.update({f"net_{k}": round(item[f"d_{k}"] - placebo[f"d_{k}"], 4) for k in ("favor", "reserve", "mean")})
        item["groups"] = _paired_groups(pairs, people)
        movers = []
        for key, cells in item["groups"].items():
            for cell in cells:
                ref = placebo_groups.get((key, cell["group"]))
                if ref:
                    cell.update({f"net_{k}": round(cell[f"d_{k}"] - ref[f"d_{k}"], 4) for k in ("favor", "reserve", "mean")})
                if not cell["small"]:
                    movers.append({"kind": KIND_LABEL[key], **cell})
        effect = "net_mean" if placebo else "d_mean"
        item["movers"] = sorted(movers, key=lambda c: (-abs(c.get(effect, c["d_mean"])), c["group"]))[:3]
        items.append(item)
    return {"baseline": {"n": len(base_rows), **_stance_stats(base_rows)}, "placebo": placebo, "items": items}


def question_priority(rows: list[dict], people: dict[str, dict], qa: list[dict], min_lift: float = 1.15) -> list[dict]:
    """How likely the panel is to ask each prepared question, and which groups ask it most (lift over the mean)."""
    out = []
    for i in range(len(qa)):
        key_i = str(i)
        mean = _mean([r["asks"][key_i] for r in rows])
        leaders = []
        for key in CLAUSE_KEYS:
            for g, ms in _grouped(rows, people, key):
                if len(ms) < SMALL_N or not mean:
                    continue
                gm = _mean([m["asks"][key_i] for m in ms])
                lift = round(gm / mean, 2)
                if lift >= min_lift:
                    leaders.append({"kind": KIND_LABEL[key], "group": g, "n": len(ms), "mean": gm, "lift": lift})
        out.append({"p": mean, "leaders": sorted(leaders, key=lambda x: (-x["lift"], -x["n"], x["group"]))[:2]})
    return out


def _group_keys(p: dict) -> list[tuple[str, str]]:
    return [("직업군", p.get("occupation_major") or "무직·기타"),
            ("연령·권역", f"{config.age_band(int(p['age']))} · {config.REGION_OF[p['province']]}"),
            ("가구", config.family_bucket(p["family_type"]))]


def outreach_candidates(rows: list[dict], people: dict[str, dict], llm_people: dict[str, dict],
                        top: int = 5, min_n: int = SMALL_N) -> list[dict]:
    """Groups to visit, from calibrated probabilities: direct impact x not supporting x not speaking up.
    member_uuids lists LLM-panel people in the same group, so their verbatim words can be quoted."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        for key in _group_keys(people[r["uuid"]]):
            groups[key].append(r)
    voices: dict[tuple[str, str], list[str]] = defaultdict(list)
    for uuid, p in llm_people.items():
        for key in _group_keys(p):
            voices[key].append(uuid)
    candidates = []
    for (kind, label), members in groups.items():
        if len(members) < min_n:
            continue
        direct = _mean([m["direct"] for m in members])
        reserve = _mean([m["reserve"] for m in members])
        silent = _mean([1 - m["comment"] for m in members])
        heard: Counter = Counter()
        for m in members:
            for key, prob in m["channel_probs"].items():
                heard[key] += prob
        candidate = {
            "kind": kind, "group": label, "n": len(members), "direct": direct, "oppose": reserve, "silent": silent,
            "score": round(direct * reserve * silent, 4),
            "channels": [CHANNELS.get(k, k) for k, _ in heard.most_common(3) if k != "none"],
            "member_uuids": sorted(voices.get((kind, label), [])),
        }
        with_methods = [m for m in members if "methods" in m]
        if with_methods:
            candidate["methods"] = _methods_of(with_methods)[:3]
        candidates.append(candidate)
    candidates.sort(key=lambda c: (-c["score"], -c["n"], c["group"]))
    picked, per_kind = [], Counter()
    for c in candidates:
        if c["score"] <= 0 or per_kind[c["kind"]] >= 2:
            continue
        picked.append(c)
        per_kind[c["kind"]] += 1
        if len(picked) >= top:
            break
    return picked


def compare(reactions: list[dict], jev_rows: dict[str, dict]) -> dict:
    """Same people, two instruments: one sampled LLM answer vs Jev's calibrated distribution."""
    pairs = [(r, jev_rows[r["uuid"]]) for r in reactions if r["uuid"] in jev_rows]
    n = len(pairs)
    if not n:
        return {"n": 0}
    llm = [float(r["support"]) for r, _ in pairs]
    jv = [j["stance"] for _, j in pairs]
    dist = Counter(int(v) for v in llm)
    corr = None
    if n > 2:
        ml, mj = sum(llm) / n, sum(jv) / n
        sl = sum((x - ml) ** 2 for x in llm) ** 0.5
        sj = sum((y - mj) ** 2 for y in jv) ** 0.5
        if sl > 0 and sj > 0:
            corr = round(sum((x - ml) * (y - mj) for x, y in zip(llm, jv)) / (sl * sj), 3)
    return {
        "n": n,
        "llm_dist": {str(k): dist.get(k, 0) for k in range(-2, 3)},
        "llm_mean": _mean(llm),
        "llm_favor": round(sum(v >= 1 for v in llm) / n, 4),
        "llm_reserve": round(sum(v <= 0 for v in llm) / n, 4),
        "jev_mass": [_mean([j["stance_probs"][i] for _, j in pairs]) for i in range(5)],
        "jev_mean": _mean(jv),
        "jev_favor": _mean([j["stance_probs"][3] + j["stance_probs"][4] for _, j in pairs]),
        "jev_reserve": _mean([j["reserve"] for _, j in pairs]),
        "corr": corr,
    }


def hearing_trajectories(reads: list[dict], participants: list[str], *, move: float = 0.5,
                         mark_threshold: float = 0.5) -> dict:
    """Each participant's stance per round as Jev read their speeches, who moved, and how often speeches
    rebut, raise new points, concede or propose (probability >= mark_threshold)."""
    by_speaker: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in reads:
        by_speaker[r["speaker"]][r["round"]].append(r["stance"])
    rows = []
    for uuid in participants:
        rounds = by_speaker.get(uuid, {})
        stances = {str(k): round(sum(v) / len(v), 4) for k, v in sorted(rounds.items())}
        values = list(stances.values())
        rows.append({"uuid": uuid, "stances": stances,
                     "change": round(values[-1] - values[0], 3) if len(values) > 1 else 0.0})
    marks = list(reads[0]["marks"]) if reads else []
    return {"participants": rows, "movers": [r["uuid"] for r in rows if abs(r["change"]) >= move],
            "counts": {k: sum(r["marks"][k] >= mark_threshold for r in reads) for k in marks}, "move": move}


def occupation_agreement(jev_map: dict[str, str], llm_map: dict[str, str], *, examples: int = 12) -> dict:
    """Two instruments classifying the same occupations into KSCO major groups."""
    both = sorted(o for o in jev_map if o in llm_map)
    agree = sum(jev_map[o] == llm_map[o] for o in both)
    return {"n": len(both), "agree": agree, "share": round(agree / len(both), 3) if both else None,
            "examples": [{"occupation": o, "jev": jev_map[o], "llm": llm_map[o]}
                         for o in both if jev_map[o] != llm_map[o]][:examples]}


def lens_summary(tags: dict[str, dict[str, float]], reactions: list[dict], labels: dict[str, str], *,
                 threshold: float = 0.5) -> dict:
    """How many reactions carry each lens (probability >= threshold) and their mean support."""
    support = {r["rid"]: r["support"] for r in reactions}
    items = []
    for key, label in labels.items():
        hit = [rid for rid, t in tags.items() if t.get(key, 0.0) >= threshold and rid in support]
        items.append({"key": key, "label": label, "n": len(hit),
                      "share": round(len(hit) / len(reactions), 3) if reactions else 0.0,
                      "mean_support": round(sum(support[r] for r in hit) / len(hit), 3) if hit else None})
    order = list(labels)
    items.sort(key=lambda it: (-it["n"], order.index(it["key"])))
    return {"items": items, "threshold": threshold}
