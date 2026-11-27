"""「찾아갈 곳」: who to go and listen to, and where they are. No model calls.

From a finished run's stored answers this picks the groups whose answers differ from everyone else's by more than
the smallest difference worth reading (the same test as the result screen, widened for the number of groups tried),
the group with the most "don't know", and a group that is split down the middle. For each it says where such people
live in the 20,000-person synthetic list and what kind of place reaches them. Venue kinds come from a fixed table;
no organisation name is ever generated.

Only attributes the model was shown split the answers: the base persona, and a life-context attribute only when the
run attached that add-on. The share with no recent petition, complaint or online post describes the group itself
(it is not an answer split), so it is shown whenever the life-context file exists.
"""
from __future__ import annotations

import gzip
import json
from collections import Counter
from statistics import NormalDist

from pp import attribution, config, visit_shared
from pp.visit_shared import (
    ADDON_GROUPS,
    ALWAYS_MISSING,
    CHILD_NEGATION,
    CHILD_OTHER_CONTEXT,
    CHILD_PARENT_CONTEXT,
    CHILDREN_NO_SPOUSE,
    DEFAULT_VENUES,
    PARTIES,
    PROVINCE,
    ROSTER_LEGACY,
    YOUNG_CHILD,
    base_groups as _base_groups,
    header,
    missing_people,
    young_child_candidate,
)

from . import panel
from .aggregate import (DIGITAL_LIMIT, MIN_GROUP, MONEY_LIMIT, UNSURE, Z_MULTI, compare_tops, int_percent,
                        result_attribution)

MAX_DIFFER, MAX_PER_OPTION, MAX_UNSURE = 3, 2, 2
OVERLAP = 0.6           # two groups sharing this much of the smaller one count as the same people
SPLIT_GAP_PP = 10.0     # top two decided options this close inside a group = "split"
PLACE_MIN = 30          # members needed before a province is named
DISTRICT_MIN = 40
ROSTER = panel.BUNDLE.parent / "roster-1m.json.gz"  # per-district counts over the 1,000,000-person list
ROSTER_DISTRICT_MIN, ROSTER_TIMES = 300, 1.3
QUIET_GAP_PP = 5        # a group's "never spoke up" share is shown only when it differs this much from everyone's
# What a card's group does not mean, by attribute: household composition is not eligibility, the digital proxy is
# information finding (not filing papers or applying in an app), drawn income bands and flags are not amounts.
CARD_CAUTIONS = {"가구": config.FAMILY_NOTE, "digital": DIGITAL_LIMIT, "kiosk_hard": DIGITAL_LIMIT,
                 "income": MONEY_LIMIT, "livelihood": MONEY_LIMIT, "basic_pension": MONEY_LIMIT}


def load_context() -> dict[str, dict]:
    if not panel.CONTEXT.exists():
        return {}
    raw = gzip.decompress(panel.CONTEXT.read_bytes()).decode("utf-8")
    return {r["uuid"]: r for r in (json.loads(x) for x in raw.splitlines() if x.strip())}


def memberships(people: list[dict], context: dict, addons: tuple[str, ...]) -> dict[tuple[str, str], dict]:
    """{(attribute, label): {"ids": set, "venues": [...], "basis": "기본"|add-on}} over `people`."""
    groups: dict[tuple[str, str], dict] = {}

    def add(attr: str, label: str, venues: list[str], basis: str, uuid: str) -> None:
        g = groups.setdefault((attr, label), {"ids": set(), "venues": venues, "basis": basis})
        g["ids"].add(uuid)

    for p in people:
        for attr, label, venues in _base_groups(p, header(p["profile"])):
            add(attr, label, venues, "기본", p["uuid"])
        row = context.get(p["uuid"])
        if not row:
            continue
        for attr, (addon, values) in ADDON_GROUPS.items():
            if addon in addons and row.get(attr) in values:
                label, venues = values[row[attr]]
                add(attr, label, venues, addon, p["uuid"])
    return groups


def _sums(ids, arm: dict, k: int) -> tuple[list[float], int]:
    total, n = [0.0] * k, 0
    for u in ids:
        row = arm.get(u)
        if row:
            n += 1
            for i in range(k):
                total[i] += row[i]
    return total, n


def _place(p: dict, h: dict) -> tuple[str, str]:
    province = PROVINCE.get(p["province"], p["province"])
    district = h.get("사는 곳", "").split(" (")[0].partition("-")[2]
    return province, f"{province} {district}".strip()


def where(ids: set, everyone: list[dict], places: dict[str, tuple[str, str]], province_group: bool) -> dict:
    """Where the group's members live in the full synthetic list: the provinces holding most of them, and the
    provinces and districts where they are a visibly larger share than nationally."""
    share = len(ids) / len(everyone)
    prov_all, dist_all = Counter(v[0] for v in places.values()), Counter(v[1] for v in places.values())
    prov, dist = Counter(places[u][0] for u in ids), Counter(places[u][1] for u in ids)
    most = [{"name": name, "pct": round(100 * n / len(ids))} for name, n in prov.most_common(3)]
    dense = sorted(({"name": name, "times": round(n / prov_all[name] / share, 1)} for name, n in prov.items()
                    if n >= PLACE_MIN and n / prov_all[name] / share >= 1.15), key=lambda x: -x["times"])[:3]
    districts = sorted(({"name": name, "times": round(n / dist_all[name] / share, 1), "n": n} for name, n in dist.items()
                        if n >= DISTRICT_MIN and n / dist_all[name] / share >= 1.5), key=lambda x: -x["times"])[:3]
    if province_group:
        most, dense = [], []
        districts = [{"name": name, "n": n, "times": None} for name, n in dist.most_common(3)]
    return {"most": most, "dense": dense, "districts": districts, "source": "panel", "people": len(ids), "of": len(everyone)}


_roster_cache: dict = {}


def load_roster() -> dict:
    """{"n", "districts": {name: n}, "groups": {label: {district: n}}} built by scripts/build_roster_1m.py, or {}."""
    if "v" not in _roster_cache:
        _roster_cache["v"] = json.loads(gzip.decompress(ROSTER.read_bytes())) if ROSTER.exists() else {}
    return _roster_cache["v"]


def where_roster(label: str, roster: dict) -> dict | None:
    """The same reading as `where`, from the 1,000,000-person list: enough people per district to name districts."""
    groups = roster.get("groups", {})
    dist = groups.get(label) or groups.get(ROSTER_LEGACY.get(label, ""))
    if not dist:
        return None
    people, total, dist_all = sum(dist.values()), roster["n"], roster["districts"]
    share = people / total
    prov, prov_all = Counter(), Counter()
    for name, n in dist_all.items():
        prov_all[name.split(" ")[0]] += n
    for name, n in dist.items():
        prov[name.split(" ")[0]] += n
    most = [{"name": name, "pct": round(100 * n / people)} for name, n in prov.most_common(3)]
    dense = sorted(({"name": name, "times": round(n / prov_all[name] / share, 1)} for name, n in prov.items()
                    if n / prov_all[name] / share >= 1.15), key=lambda x: -x["times"])[:3]
    districts = sorted(({"name": name, "times": round(n / dist_all[name] / share, 1), "n": n} for name, n in dist.items()
                        if n >= ROSTER_DISTRICT_MIN and n / dist_all[name] / share >= ROSTER_TIMES),
                       key=lambda x: -x["times"])[:5]
    return {"most": most, "dense": dense, "districts": districts, "source": "1m", "people": people, "of": total}


def _short(option: str, limit: int = 20) -> str:
    return option if len(option) <= limit else option[:limit].rstrip(" ,") + "…"


def _questions(kind: str, question: str, option: str | None) -> list[str]:
    if kind == "unsure":
        return ["이 정책에 대해 들어 보신 적이 있습니까?", "무엇을 알면 판단하실 수 있겠습니까?",
                "본인이나 가족의 생활과 닿는 부분이 있다면 어디입니까?"]
    if kind == "split":
        return [question, "같은 처지의 사람들 사이에서도 생각이 갈립니다. 어떤 점에서 갈린다고 보십니까?",
                "어떤 조건이 붙으면 받아들일 수 있겠습니까?"]
    return [question, f"‘{_short(option)}’ 쪽으로 생각하신다면, 가장 큰 이유는 무엇입니까?",
            "어떤 점이 바뀌면 생각이 달라지시겠습니까?"]


def view(spec: dict, people: list[dict], answers: dict, options: list[str], panel_version: str | None,
         everyone: list[dict] | None = None, context: dict | None = None, roster: dict | None = None) -> dict:
    """The visit view of one finished run. `people` is the run's sample, `everyone` the full list (for places)."""
    from pp import diagnostics as pp_diag, life_context

    everyone = everyone if everyone is not None else panel.load(addons="off")[0]
    context = context if context is not None else load_context()
    roster = roster if roster is not None else load_roster()
    addons = life_context.addons_from_version(panel_version)
    k = len(options)
    main, placebo, rev = answers.get("main", {}), answers.get("placebo", {}), answers.get("reversed", {})
    sample = [p for p in people if p["uuid"] in main]
    groups = memberships(sample, context, addons)
    unsure = [i for i, o in enumerate(options) if UNSURE.search(o)]
    decided = [i for i in range(k) if i not in unsure]
    all_ids = [p["uuid"] for p in sample]
    totals = {name: _sums(all_ids, arm, k) for name, arm in (("main", main), ("placebo", placebo), ("reversed", rev))}
    overall = [x / max(1, totals["main"][1]) for x in totals["main"][0]]
    top = max(decided, key=lambda i: overall[i]) if decided else 0

    usable = {key: g for key, g in groups.items()
              if len(g["ids"]) >= MIN_GROUP and len(sample) - len(g["ids"]) >= MIN_GROUP}
    tests = len(usable) * k
    z = max(Z_MULTI, NormalDist().inv_cdf(1 - 0.05 / (2 * tests))) if tests else Z_MULTI

    def tops(sums: dict, i: int) -> dict:
        share = lambda name: sums[name][0][i] / max(1, sums[name][1])  # noqa: E731
        return {"n": sums["main"][1], "top_share": share("main"), "placebo_top": share("placebo"),
                "reversed_top": share("reversed")}

    rows = []  # one per usable group
    for key, g in usable.items():
        own = {name: _sums(g["ids"], arm, k) for name, arm in (("main", main), ("placebo", placebo), ("reversed", rev))}
        rest = {name: ([t - o for t, o in zip(totals[name][0], own[name][0])], totals[name][1] - own[name][1]) for name in own}
        gaps = [compare_tops(tops(own, i), tops(rest, i), z) for i in range(k)]
        shares = [x / max(1, own["main"][1]) for x in own["main"][0]]
        rows.append({"key": key, "g": g, "gaps": gaps, "shares": shares, "n": own["main"][1]})

    readable = lambda c: abs(c["diff"]) > c["threshold"]  # noqa: E731
    chosen: list[dict] = []

    def overlaps(row: dict) -> bool:
        return any(len(row["g"]["ids"] & c["row"]["g"]["ids"]) / min(len(row["g"]["ids"]), len(c["row"]["g"]["ids"])) > OVERLAP
                   or (row["key"][0] == c["row"]["key"][0] and c["kind"] == "differ" and row["key"][0] in ("권역", "성별"))
                   for c in chosen)

    differ = sorted(((r, i) for r in rows for i in decided if r["gaps"][i]["diff"] > 0 and readable(r["gaps"][i])),
                    key=lambda x: (x[1] == top, -x[0]["gaps"][x[1]]["diff"]))  # views other than the majority's first
    per_option: Counter = Counter()
    for r, i in differ:
        if sum(c["kind"] == "differ" for c in chosen) >= MAX_DIFFER:
            break
        if per_option[i] >= MAX_PER_OPTION or overlaps(r):
            continue
        per_option[i] += 1
        chosen.append({"kind": "differ", "row": r, "option": i})
    for i in unsure[:1]:
        best = sorted((r for r in rows if r["gaps"][i]["diff"] > 0 and readable(r["gaps"][i])), key=lambda r: -r["gaps"][i]["diff"])
        for r in best:
            if sum(c["kind"] == "unsure" for c in chosen) >= MAX_UNSURE:
                break
            if not overlaps(r):
                chosen.append({"kind": "unsure", "row": r, "option": i})
    if len(decided) >= 2:
        def gap(shares: list[float]) -> tuple[float, int, int]:
            a, b = sorted(decided, key=lambda i: -shares[i])[:2]
            return 100 * (shares[a] - shares[b]), a, b
        if gap(overall)[0] > SPLIT_GAP_PP:
            tight = sorted((r for r in rows if gap(r["shares"])[0] <= SPLIT_GAP_PP), key=lambda r: gap(r["shares"])[0])
            pick = next((r for r in tight if not overlaps(r)), None)
            if pick:
                chosen.append({"kind": "split", "row": pick, "option": gap(pick["shares"])[1], "other": gap(pick["shares"])[2]})

    # Places come from the full list, so a small run still gets usable geography.
    full_groups = memberships(everyone, context, addons) if chosen else {}
    places = {p["uuid"]: _place(p, header(p["profile"])) for p in everyone} if chosen else {}

    def quiet_of(ids) -> int | None:
        """Share with no petition signature, complaint to an official or online post in the past year."""
        known = [context[u] for u in ids if u in context and context[u].get("petition") is not None]
        if len(known) < MIN_GROUP:
            return None
        return round(100 * sum(not (c.get("petition") or c.get("online_voice") or c.get("contacted_official"))
                               for c in known) / len(known))

    quiet_all = quiet_of([p["uuid"] for p in everyone])

    cards = []
    for c in chosen:
        r, i = c["row"], c["option"]
        g, cmp_ = r["g"], r["gaps"][i]
        label = r["key"][1]
        mine, rest_pct = round(100 * cmp_["a"]["top_share"]), round(100 * cmp_["b"]["top_share"])
        if c["kind"] == "differ":
            title = f"‘{_short(options[i])}’ 쪽이 더 많은 사람"
            say = f"‘{options[i]}’ {mine}% — 나머지 사람들({rest_pct}%)보다 {cmp_['diff']:+.1f}%p"
        elif c["kind"] == "unsure":
            title = "아직 판단하지 못한 사람"
            say = f"‘{options[i]}’ {mine}% — 나머지 사람들({rest_pct}%)보다 {cmp_['diff']:+.1f}%p. 내용이 닿지 않았거나 판단할 근거가 부족합니다"
        else:
            j = c["other"]
            title = "의견이 갈린 사람"
            say = (f"‘{options[i]}’ {round(100 * r['shares'][i])}% 대 ‘{options[j]}’ {round(100 * r['shares'][j])}% — "
                   "이 사람들 안에서 생각이 갈립니다")
        also = None
        if c["kind"] != "split":
            low = min((x for x in decided if x != i and r["gaps"][x]["diff"] < 0 and readable(r["gaps"][x])),
                      key=lambda x: r["gaps"][x]["diff"], default=None)
            if low is not None:
                also = f"‘{_short(options[low])}’ 쪽은 {abs(r['gaps'][low]['diff']):.1f}%p 적습니다"
        full = full_groups.get(r["key"], {"ids": set()})["ids"]
        quiet = quiet_of(full) if full else None
        cards.append({
            "kind": c["kind"], "title": title, "group": label, "attribute": r["key"][0], "n": r["n"],
            "say": say, "also": also, "percent": int_percent(r["shares"]),
            "stat": {"option": options[i], "group_pct": mine, "rest_pct": rest_pct, "diff_pp": round(cmp_["diff"], 1),
                     "threshold_pp": round(cmp_["threshold"], 1), "parts": {n: round(v, 1) for n, v in cmp_["parts"].items()}},
            "where": (g["basis"] == "기본" and where_roster(label, roster))
            or (where(full, everyone, places, r["key"][0] == "시도") if len(full) >= MIN_GROUP else None),
            "venues": g["venues"],
            "quiet": ({"group_pct": quiet, "all_pct": quiet_all} if quiet is not None and quiet_all is not None
                      and abs(quiet - quiet_all) >= QUIET_GAP_PP else None),
            "questions": _questions(c["kind"], spec.get("question", ""), options[i]),
            "basis": "기본 인물 정보" if g["basis"] == "기본" else f"생활 여건 자료({life_context.ADDONS[g['basis']]['title']})",
            "caution": " ".join(x for x in (CARD_CAUTIONS.get(r["key"][0]),
                      pp_diag.EDU_INCOME_CARD_CAUTION if r["key"][0] in ("학력", "income") else None) if x) or None,
        })

    regional = [r for r in rows if r["key"][0] in ("권역", "시도") and any(readable(c) for c in r["gaps"])]
    region_note = None
    if rows and not regional:
        region_note = "사는 지역에 따른 차이는 믿을 수 있는 최소 차이를 넘지 않았습니다. 어디에 사느냐보다 어떤 처지냐에서 갈립니다."
    text = " ".join(str(spec.get(x, "")) for x in ("title", "policy_text", "question"))
    missing = missing_people(text)
    small = None
    if not cards:
        small = (f"{len(sample):,}명의 답으로는 따로 찾아갈 집단이 가려지지 않았습니다. "
                 + ("인원을 2,000명 이상으로 늘려 다시 물으면 더 작은 집단까지 볼 수 있습니다." if len(sample) < 2000
                    else "집단 사이 차이가 믿을 수 있는 최소 차이를 넘지 않습니다."))
    method = [
        f"기본 인물 정보{'와 이 실행에 붙인 생활 여건 자료' if addons else ''}로 나눈 {len(usable)}개 집단을 각각 나머지 사람들과 견줬습니다"
        f"(집단 {len(usable)}개 × 선택지 {k}개 = {tests}번 비교).",
        "비교 횟수가 많을수록 우연히 생기는 차이도 늘어나므로, 표본 오차 폭을 비교 횟수에 맞춰 넓혔습니다. "
        "통제 문장·선택지 순서를 바꿨을 때 두 집단이 다르게 움직인 폭과 3%p 가운데 가장 큰 값을 넘는 차이만 카드로 만들었습니다.",
        "답은 이 실행의 합성 인물에게서, 사는 곳은 더 큰 명단에서 찾았습니다. 기본 인물 정보로 나눈 집단은 합성 인물 100만 명 "
        "명단(시군구마다 평균 약 4천 명)에서, 생활 여건 자료로 나눈 집단은 그 자료가 붙은 2만 명 명단에서 셉니다. "
        "2만 명 기준 시군구는 인원이 적어 참고용입니다.",
        "만날 곳은 집단 유형별로 미리 정해 둔 기관 종류이며, 특정 기관을 추천하는 것이 아닙니다.",
        "합성 인물의 답은 실제 국민의 응답이 아닙니다. 이 화면은 누구를 먼저 만날지 정하는 데 쓰고, 결론은 실제로 만나서 들은 말로 내리십시오.",
    ]
    diag = pp_diag.diagnose_survey({**spec, "options": options}, sample, main, context=context)
    lines = [f"{c['group']}({c['n']:,}명): {c['say']}. 만날 곳: {', '.join(c['venues'])}." for c in cards]
    credit = result_attribution(panel_version, list(addons))
    cautions = list(dict.fromkeys(c["caution"] for c in cards if c["caution"]))
    copy_text = ("찾아갈 곳(합성 인물 기준, 실제 조사 아님) — " + " / ".join(lines)
                 + "".join(f" 주의: {x}" for x in cautions) + f" {attribution.short(credit)}") if lines else (small or "")
    return {"cards": cards, "missing": missing, "region_note": region_note, "small": small, "groups": len(usable),
            "tests": tests, "n": len(sample), "quiet_all_pct": quiet_all, "roster_n": roster.get("n"), "method": method,
            "diagnostics": diag, "warnings": [*diag["reliability_findings"], *diag["warnings"]],
            "copy_text": copy_text, "attribution": credit}
