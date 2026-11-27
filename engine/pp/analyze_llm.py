"""LLM-assisted grouping with strict id validation. Every quote is copied by code, never by the LLM."""
from __future__ import annotations

import json
from collections import Counter

from . import config, llm, prompts

LIFT_KEYS = (
    ("연령", lambda p: config.age_band(int(p["age"]))),
    ("직업군", lambda p: p.get("occupation_major") or "무직·기타"),
    ("권역", lambda p: config.REGION_OF[p["province"]]),
)


def validate_clusters(data: dict, known_ids: set[str], max_k: int = 8, min_valid: int = 1) -> list[dict]:
    items = data.get("issues")
    if not isinstance(items, list):
        raise ValueError("no issues list")
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        members = []
        for member in item.get("member_ids") or []:
            member = str(member).strip()
            if member in known_ids and member not in seen:
                members.append(member)
                seen.add(member)
        if not title or not members:
            continue
        stance = item.get("stance") if item.get("stance") in config.STANCES else "혼재"
        out.append({"title": title[:40], "stance": stance,
                    "summary": str(item.get("summary") or "").strip()[:200], "member_ids": members})
        if len(out) >= max_k:
            break
    if len(out) < min_valid:
        raise ValueError(f"only {len(out)} valid clusters")
    return out


def cluster_issues(reactions: list[dict], title: str, model: str | None = None) -> list[dict]:
    known = {r["rid"] for r in reactions}
    lines = "\n".join(f"{r['rid']}|지지 {r['support']}|{r['reason']}|우려: {', '.join(r['concerns']) or '없음'}"
                      for r in reactions)
    min_valid = min(3, len(known))
    return llm.complete_json(
        "cluster", prompts.CLUSTER_SYSTEM, prompts.cluster_prompt(title, lines, 5, 8),
        model=model or config.SYNTH_MODEL,
        validate=lambda d: {"issues": validate_clusters(d, known, 8, min_valid)},
    )["issues"]


def enrich_issues(issues: list[dict], reactions: list[dict], people: dict[str, dict]) -> list[dict]:
    """Add ids, counts, over-represented groups, verbatim quotes and top segments."""
    by_rid = {r["rid"]: r for r in reactions}
    rep = [r for r in reactions if people[r["uuid"]].get("panel", "rep") == "rep"]
    aff = [r for r in reactions if people[r["uuid"]].get("panel") == "aff"]
    total = len(rep)
    base = {name: Counter(fn(people[r["uuid"]]) for r in rep) for name, fn in LIFT_KEYS}
    out = []
    ranked = sorted(issues, key=lambda it: (-sum(people[by_rid[rid]["uuid"]].get("panel", "rep") == "rep"
                                                for rid in it["member_ids"]), it["title"]))
    for i, issue in enumerate(ranked, start=1):
        members = [by_rid[m] for m in issue["member_ids"]]
        n = len(members)
        mean = sum(m["support"] for m in members) / n
        by_panel = {}
        for key, pool in (("rep", rep), ("aff", aff)):
            selected = [r for r in members if people[r["uuid"]].get("panel", "rep") == key]
            by_panel[key] = {"n": len(selected), "denominator": len(pool),
                             "share": round(len(selected) / len(pool), 3) if pool else None,
                             "mean": round(sum(r["support"] for r in selected) / len(selected), 3) if selected else None}
        by_panel["aff"]["caution"] = "전체 비율로 읽지 않음"
        rep_members = [m for m in members if people[m["uuid"]].get("panel", "rep") == "rep"]
        groups = []
        for name, fn in LIFT_KEYS:
            for label, count in Counter(fn(people[m["uuid"]]) for m in rep_members).items():
                lift = (count / len(rep_members)) / (base[name][label] / total)
                if count >= 3 and lift >= 1.3:
                    groups.append({"kind": name, "group": label, "count": count, "lift": round(lift, 2)})
        groups.sort(key=lambda g: (-g["lift"], -g["count"], g["group"]))
        quotes, bands = [], set()
        # Jev membership probability first (when present), then closeness to the issue's mean stance.
        probs = issue.get("member_probs", {})
        for m in sorted(members, key=lambda m: (-probs.get(m["rid"], 0.0), abs(m["support"] - mean), m["rid"])):
            band = config.age_band(int(people[m["uuid"]]["age"]))
            if band in bands:
                continue
            bands.add(band)
            quotes.append({"rid": m["rid"], "uuid": m["uuid"], "text": m["reason"]})
            if len(quotes) == 3:
                break
        segs = Counter(m["segment_id"] for m in members if m.get("segment_id"))
        out.append({"id": f"i{i}", **issue, "n": by_panel["rep"]["n"], "share": by_panel["rep"]["share"],
                    "mean": by_panel["rep"]["mean"], "by_panel": by_panel, "basis": "rep",
                    "groups": groups[:4], "quotes": quotes, "segments": [s for s, _ in segs.most_common(3)]})
    return out


def cluster_suggestions(reactions: list[dict], title: str, model: str | None = None) -> list[dict]:
    items = [r for r in reactions if r.get("suggestion")]
    by_rid = {r["rid"]: r for r in items}
    if len(items) < 5:
        return [{"title": r["suggestion"][:30], "stance": "혼재", "summary": "", "member_ids": [r["rid"]],
                 "n": 1, "example": r["suggestion"]} for r in items]
    known = set(by_rid)
    lines = "\n".join(f"{r['rid']}|{r['suggestion']}" for r in items)
    clusters = llm.complete_json(
        "cluster", prompts.CLUSTER_SYSTEM, prompts.cluster_prompt(title, lines, 3, 8, what="보완 제안"),
        model=model or config.SYNTH_MODEL,
        validate=lambda d: {"issues": validate_clusters(d, known, 8, 1)},
    )["issues"]
    return [{**c, "n": len(c["member_ids"]), "example": by_rid[c["member_ids"][0]]["suggestion"]}
            for c in sorted(clusters, key=lambda c: -len(c["member_ids"]))]


def draft_amendments(suggestions: list[dict], title: str, policy_text: str, segments: list[dict], k: int = 3,
                     model: str | None = None) -> list[dict]:
    """Turn the largest suggestion groups into one concrete amendment sentence each (AI-written),
    for the paired Jev test. Source names, sizes and examples come from the data, not the model."""
    top = sorted(suggestions, key=lambda c: -c["n"])[:k]
    if not top:
        return []
    known_segments = {s["id"] for s in segments}
    sources = {f"c{i}": c for i, c in enumerate(top)}
    seg_lines = "\n".join(f"{s['id']}|{s['label']}" for s in segments)
    sug_lines = "\n".join(f"{cid}|{c['title']}|대표 {c['n']}명 · 영향권 {c.get('n_aff', 0)}명(전체 비율로 읽지 않음)|{c['example']}"
                          for cid, c in sources.items())

    def validate(d):
        items = d.get("items")
        if not isinstance(items, list):
            raise ValueError("no items")
        by_source = {}
        for it in items:
            if not isinstance(it, dict) or it.get("source") not in sources or it["source"] in by_source:
                continue
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            if not text.startswith("[수정안]"):
                text = "[수정안] " + text
            seg = it.get("segment") if it.get("segment") in known_segments else None
            by_source[it["source"]] = {"title": str(it.get("title") or "").strip()[:30] or sources[it["source"]]["title"],
                                       "text": text[:300], "segment_id": seg}
        missing = [cid for cid in sources if cid not in by_source]
        if missing:
            raise ValueError(f"missing amendments for {missing}")
        return by_source

    drafted = llm.complete_json("amend", prompts.AMEND_SYSTEM,
                                prompts.amend_prompt(title, policy_text, seg_lines, sug_lines),
                                model=model or config.SYNTH_MODEL, validate=validate)
    return [{"id": f"a{i + 1}", **drafted[cid], "source_title": c["title"], "source_n": c["n"],
             "source_n_aff": c.get("n_aff", 0), "source_example": c["example"]} for i, (cid, c) in enumerate(sources.items())]


def map_occupations(occupations: list[str], model: str | None = None) -> dict[str, str]:
    """Free-text occupation -> KSCO major group, cached on the SSD across runs."""
    path = config.occupation_cache(mock=llm.provider() == "mock")
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    todo = sorted({o for o in occupations if o not in cache})
    for start in range(0, len(todo), 80):
        chunk = todo[start:start + 80]

        def validate(d, chunk=chunk):
            mapping = d.get("map")
            if not isinstance(mapping, dict):
                raise ValueError("no map")
            return {o: mapping[o] if mapping.get(o) in config.OCCUPATION_MAJORS else "무직·기타" for o in chunk}

        cache.update(llm.complete_json("occupation", prompts.OCC_SYSTEM, prompts.occupation_prompt(chunk),
                                       model=model or config.SYNTH_MODEL, validate=validate))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    return {o: cache[o] for o in occupations}


def outreach_text(cands: list[dict], reactions_by_uuid: dict[str, dict], title: str,
                  model: str | None = None) -> list[dict]:
    """Attach verbatim quotes and an AI-suggested way to reach each group.

    The prompt sees only opposed or neutral reasons. The card quotes the group's most reserved members
    (lowest support, then most concerns), never repeating a quote already shown for an earlier group."""
    if not cands:
        return []
    enriched, blocks, used = [], [], set()
    for cand in cands:
        members = [reactions_by_uuid[u] for u in cand["member_uuids"]]
        ranked = sorted(members, key=lambda r: (r["support"], -len(r.get("concerns") or []), r["rid"]))
        blocks.append(prompts.outreach_block(cand, [r["reason"] for r in ranked if r["support"] <= 0][:3]))
        picks = [r for r in ranked if r["reason"] not in used][:2]
        used.update(r["reason"] for r in picks)
        enriched.append({**cand, "sample_quotes": [r["reason"] for r in picks], "sample_uuids": [r["uuid"] for r in picks]})
    labels = [c["group"] for c in cands]

    def validate(d):
        items = d.get("items")
        if not isinstance(items, list):
            raise ValueError("no items")
        by_group = {str(it.get("group", "")).strip(): it for it in items if isinstance(it, dict)}
        missing = [g for g in labels if g not in by_group]
        if missing:
            raise ValueError(f"missing groups: {missing}")
        return {"items": [{k: str(by_group[g].get(k) or "").strip()[:160] for k in ("method", "where", "when", "why")}
                          for g in labels]}

    items = llm.complete_json("outreach", prompts.OUTREACH_SYSTEM, prompts.outreach_prompt(title, blocks),
                              model=model or config.SYNTH_MODEL, validate=validate)["items"]
    return [{**e, "suggestion": s} for e, s in zip(enriched, items)]


def plan_qa(issues: list[dict], title: str, model: str | None = None) -> list[dict]:
    if not issues:
        return []
    ids = {it["id"] for it in issues}
    lines = "\n".join(f"{it['id']}|{it['title']}|{it['summary']}" for it in issues[:6])

    def validate(d):
        items = d.get("items")
        if not isinstance(items, list):
            raise ValueError("no items")
        out = [{"question": str(it.get("question") or "").strip()[:200],
                "answer": str(it.get("answer") or "").strip()[:300], "issue_id": it.get("issue_id")}
               for it in items if isinstance(it, dict) and it.get("issue_id") in ids and it.get("question")]
        if not out:
            raise ValueError("no valid qa items")
        return {"items": out[:6]}

    return llm.complete_json("qa", prompts.QA_SYSTEM, prompts.qa_prompt(title, lines),
                             model=model or config.SYNTH_MODEL, validate=validate)["items"]
