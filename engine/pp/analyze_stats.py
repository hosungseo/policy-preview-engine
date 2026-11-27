"""Deterministic statistics over reactions. No LLM here, so every number is reproducible."""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from . import config

SMALL_N = 10
GROUPINGS = {
    "age_band": lambda p: config.age_band(int(p["age"])),
    "region": lambda p: config.REGION_OF[p["province"]],
    "sex": lambda p: p["sex"],
    "education_level": lambda p: p["education_level"],
    "housing_type": lambda p: p["housing_type"],
    "family": lambda p: config.family_bucket(p["family_type"]),
    "occupation_major": lambda p: p.get("occupation_major") or "무직·기타",
}
ORDER = {
    "age_band": [b[2] for b in config.AGE_BANDS],
    "region": config.REGIONS,
    "sex": ["남자", "여자"],
    "education_level": config.EDUCATION_ORDER,
    "housing_type": config.HOUSING_ORDER,
    "family": config.FAMILY_BUCKETS,
    "occupation_major": config.OCCUPATION_MAJORS,
}


def pct(x: float | None) -> str:
    """A non-zero share never reads as 0%, and a partial share never reads as 100%."""
    if x is None:
        return "불명"
    whole = round(x * 100)
    if (x > 0 and whole == 0) or (x < 1 and whole == 100):
        fine = f"{x * 100:.1f}"
        if x > 0 and float(fine) == 0:
            return "<0.1%"
        if x < 1 and float(fine) == 100:
            return ">99.9%"
        return f"{fine}%"
    return f"{whole}%"


def signed(x: float) -> str:
    return f"{x:+.2f}"


def overall(reactions: list[dict], seed: int = 7, boots: int = 2000) -> dict:
    values = [r["support"] for r in reactions]
    n = len(values)
    dist = Counter(values)
    base = {"n": n, "dist": {str(k): dist.get(k, 0) for k in range(-2, 3)}}
    if n == 0:
        return {**base, "mean": None, "ci95": None}
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(boots))
    return {**base, "mean": round(sum(values) / n, 3),
            "ci95": [round(means[int(0.025 * boots)], 3), round(means[int(0.975 * boots) - 1], 3)]}


def by_group(reactions: list[dict], people: dict[str, dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for key, label_of in GROUPINGS.items():
        acc: dict[str, list[int]] = defaultdict(list)
        for r in reactions:
            acc[label_of(people[r["uuid"]])].append(r["support"])
        rows = []
        for group in ORDER[key] + sorted(set(acc) - set(ORDER[key])):
            values = acc.get(group)
            if not values:
                continue
            n = len(values)
            rows.append({"group": group, "n": n, "mean": round(sum(values) / n, 3),
                         "oppose": round(sum(v < 0 for v in values) / n, 3),
                         "favor": round(sum(v > 0 for v in values) / n, 3),
                         "small": n < SMALL_N})
        out[key] = rows
    return out


def segment_heat(reactions: list[dict], segments: list[dict]) -> list[dict]:
    rows = []
    for seg in segments:
        hits = [r for r in reactions if r.get("segment_id") == seg["id"]]
        concerns = Counter(c for r in hits for c in r.get("concerns", []))
        rows.append({
            "segment_id": seg["id"],
            "mentions": len(hits),
            "mean": round(sum(r["support"] for r in hits) / len(hits), 3) if hits else None,
            "oppose": sum(r["support"] < 0 for r in hits),
            "favor": sum(r["support"] > 0 for r in hits),
            "top_concerns": [c for c, _ in concerns.most_common(5)],
        })
    return rows


def outreach_candidates(reactions: list[dict], people: dict[str, dict], top: int = 5, min_n: int = 5) -> list[dict]:
    """Groups to visit: directly affected x opposed x unlikely to speak up (AI-estimated)."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in reactions:
        p = people[r["uuid"]]
        groups[("직업군", p.get("occupation_major") or "무직·기타")].append(r)
        groups[("연령·권역", f"{config.age_band(int(p['age']))} · {config.REGION_OF[p['province']]}")].append(r)
        groups[("가구", config.family_bucket(p["family_type"]))].append(r)
    rows = []
    for (kind, label), rs in groups.items():
        n = len(rs)
        if n < min_n:
            continue
        direct = sum(r["impact"] == "직접" for r in rs) / n
        oppose = sum(r["support"] <= 0 for r in rs) / n  # not supporting: opposed or neutral (반대·유보)
        silent = sum(not r["would_comment"] for r in rs) / n
        heard = Counter(r["channel"] for r in rs if r.get("channel") and r["channel"] != "없음")
        rows.append({"kind": kind, "group": label, "n": n, "direct": round(direct, 3), "oppose": round(oppose, 3),
                     "silent": round(silent, 3), "score": round(direct * oppose * silent, 4),
                     "channels": [c for c, _ in heard.most_common(4)], "member_uuids": [r["uuid"] for r in rs]})
    rows.sort(key=lambda x: (-x["score"], -x["n"], x["group"]))
    picked: list[dict] = []
    per_kind: Counter = Counter()
    for row in rows:
        if row["score"] <= 0 or per_kind[row["kind"]] >= 2:
            continue
        picked.append(row)
        per_kind[row["kind"]] += 1
        if len(picked) >= top:
            break
    return picked


def insights(analysis: dict, segments: list[dict]) -> list[str]:
    """Headline sentences built from computed numbers only (labelled '코드 자동 요약' in the UI)."""
    lines: list[str] = []
    if analysis.get("issues"):
        top = max(analysis["issues"], key=lambda it: it.get("n", it.get("share") or 0))
        lines.append(f"대표 패널에서 가장 많이 나온 쟁점은 ‘{top['title']}’입니다. 대표 패널 반응의 {pct(top['share'])}가 여기에 속합니다.")
    heat = sorted((h for h in analysis.get("segments_heat", []) if h["mentions"]), key=lambda h: -h["mentions"])
    labels = {s["id"]: s["label"] for s in segments}
    if heat:
        h = heat[0]
        lines.append(f"대표 패널에서 반응을 가장 많이 일으킨 부분은 ‘{labels.get(h['segment_id'], h['segment_id'])}’입니다"
                     f"({h['mentions']}건, 평균 지지 {signed(h['mean'])}).")
    cands = [row for rows in analysis.get("by_group", {}).values() for row in rows if not row["small"]]
    if cands:
        low = min(cands, key=lambda row: row["mean"])
        lines.append(f"대표 패널에서 지지가 가장 낮은 집단은 {low['group']}입니다(평균 {signed(low['mean'])}, {low['n']}명).")
    rep, aff = analysis.get("overall", {}), analysis.get("overall_aff", {})
    if rep.get("n") and aff.get("n"):
        diff = aff["mean"] - rep["mean"]
        if abs(diff) < 0.05:
            lines.append(f"영향권 패널과 대표 패널의 평균 지지는 비슷합니다({signed(aff['mean'])} 대 {signed(rep['mean'])}).")
        else:
            word = "낮습니다" if diff < 0 else "높습니다"
            lines.append(f"영향권 패널의 평균 지지({signed(aff['mean'])})가 대표 패널({signed(rep['mean'])})보다 {abs(diff):.2f} {word}.")
    jv = analysis.get("jev")
    if jv and jv.get("n"):
        mass = jv["overall"]["mass"]
        line = (f"{jv['n']:,}명 정량 점검(Jev)에서 찬성 쪽 확률은 평균 {pct(mass[3] + mass[4])}, "
                f"반대·유보 쪽은 {pct(mass[0] + mass[1] + mass[2])}입니다.")
        cmp = jv.get("compare") or {}
        if cmp.get("n"):
            # a head count, not a rounded share: 399 of 400 must not read as "100%"
            favor_n = sum(cmp.get("llm_dist", {}).get(k, 0) for k in ("1", "2"))
            line += (f" 같은 {cmp['n']:,}명 중 LLM은 {favor_n:,}명이 찬성으로 답했고, "
                     f"Jev는 이 {cmp['n']:,}명의 찬성 쪽 확률을 평균 {pct(cmp['jev_favor'])}로 봤습니다.")
        lines.append(line)
        positions = jv.get("positions")
        if positions and positions.get("overall"):
            sid, cell = max(positions["overall"].items(), key=lambda kv: kv[1]["oppose"])
            if cell["oppose"] >= 0.1:
                line = f"조항별로는 ‘{labels.get(sid, sid)}’에 반대할 확률이 가장 높습니다({pct(cell['oppose'])})."
                groups = [g for rows in positions.get("groups", {}).values() for g in rows if not g["small"]]
                if groups:
                    worst = max(groups, key=lambda g: g["oppose"][sid])
                    line += f" 가장 높은 집단은 {worst['group']}({pct(worst['oppose'][sid])})입니다."
            else:
                low_sid, low = min(positions["overall"].items(), key=lambda kv: kv[1]["support"])
                line = (f"반대 확률이 10%를 넘은 조항은 없습니다. 찬성 확률이 가장 낮은 조항은 "
                        f"‘{labels.get(low_sid, low_sid)}’입니다({pct(low['support'])}).")
            lines.append(line)
    if analysis.get("outreach"):
        g = analysis["outreach"][0]
        line = (f"찾아가 들어야 할 첫 집단은 {g['group']}입니다. {g['n']}명 중 반대·유보 {pct(g['oppose'])}, "
                f"스스로 의견을 내지 않을 사람 {pct(g['silent'])}입니다(AI 추정 포함).")
        if g.get("panel") == "aff":
            line += " 영향권 패널 내부 수치이며 전체 비율로 읽지 않음."
        if g.get("methods"):
            m = g["methods"][0]
            line += f" 이 집단은 ‘{m['label']}’ 참여 확률이 가장 높습니다({pct(m['p'])})."
        lines.append(line)
    alts = analysis.get("alternatives") or {}
    if alts.get("items"):
        effect = "net_reserve" if alts.get("placebo") else "d_reserve"  # net of merely appending a sentence
        best = min(alts["items"], key=lambda it: it.get(effect, it["d_reserve"]))
        change = best.get(effect, best["d_reserve"])
        basis = "내용 없는 대조 문장의 변화를 뺀 값, " if effect == "net_reserve" else ""
        if change < 0:
            lines.append(f"보완 제안으로 만든 수정안 {len(alts['items'])}개 중 ‘{best['title']}’가 반대·유보를 가장 많이 줄였습니다"
                         f"({change * 100:+.1f}%p, {basis}같은 {alts['n']:,}명 비교, Jev 추정).")
        else:
            lines.append(f"보완 제안으로 만든 수정안 {len(alts['items'])}개 모두 반대·유보를 줄이지 못했습니다"
                         f"(같은 {alts['n']:,}명 비교, Jev 추정).")
    clarity = analysis.get("clarity") or {}
    if clarity.get("clauses"):
        line = f"정책문 명료성 점검에서 조항 {clarity['clauses']}개 중 {clarity['flagged']}개가 문제 지표에 걸렸습니다."
        worst = clarity.get("worst")
        if worst:
            line += f" 가장 많이 걸린 조항은 ‘{labels.get(worst['segment_id'], worst['segment_id'])}’({'·'.join(worst['flags'])})입니다."
        if clarity.get("missing"):
            line += f" 안내가 빠진 것으로 보이는 항목: {', '.join(clarity['missing'])}(Jev 점검)."
        lines.append(line)
    cons = analysis.get("consistency") or {}
    if cons.get("n"):
        lines.append(f"LLM 응답 {cons['n']:,}건 중 {cons['flagged']:,}건은 이유 문장과 스스로 붙인 찬반이 "
                     f"{cons['threshold']:g}단계 이상 어긋나 따로 표시했습니다(Jev 판독).")
    return lines
