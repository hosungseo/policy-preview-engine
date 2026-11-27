"""Housing context for panel members: a tenure (자가·전세·월세·무상) drawn from official statistics, and a block of
local housing-market facts at a measure's announcement, for the Jev state.

Tenure probabilities combine two 2020 census tables for the person's district — tenure by housing type and tenure by
household-head age (single-person households use their own table) — then each province is scaled to the 2024 housing
survey's owner/renter/rent-free shares. The draw is seeded by the person's uuid, so a person keeps one tenure across
measures and runs. Everything here is an assumption made from statistics, not a fact about the person, and the block
is labelled as drawn from official statistics.
"""
from __future__ import annotations

import hashlib
import json
import random
from functools import lru_cache
from pathlib import Path

from . import config

OFFICIAL = Path(__file__).resolve().parents[1] / "series" / "official"
TENURES = ("own", "jeonse", "monthly", "free")
TENURE_KO = {"own": "자가", "jeonse": "전세", "monthly": "월세", "free": "무상(관사·사택 등)"}
# persona housing_type -> census 거처 종류 and real-transaction type
CENSUS_HOUSING = {"아파트": "아파트", "단독주택": "단독주택", "연립주택": "연립주택", "다세대주택": "다세대주택",
                  "비주거용 건물 내 주택": "비주거용 건물 내 주택", "주택 이외의 거처": "주택이외의 거처-계"}
MARKET_TYPE = {"아파트": "Apt", "연립주택": "RH", "다세대주택": "RH", "단독주택": "SH",
               "비주거용 건물 내 주택": "SH", "주택 이외의 거처": "Offi"}
MARKET_TYPE_KO = {"Apt": "아파트", "RH": "연립·다세대", "SH": "단독·다가구", "Offi": "오피스텔"}
SINGLE = {"혼자 거주", "혼자 거주 (배우자 별거)"}
# The person lives in a parent's (or grandparent's) household, so the household head is a generation older.
PARENT_HOUSEHOLD = ("부모와 동거", "어머니와 동거", "아버지와 동거", "부모·조모와 동거", "부모·형제자매와 동거",
                    "부모·조부모와 동거", "부모·조부와 동거", "부모·친인척과 동거", "부 또는 모와 거주")
GRANDPARENT_HOUSEHOLD = ("조부 또는 조모와 동거", "조부모와 동거")
SMOOTH = 0.5  # added to every census count so an empty cell does not zero a tenure out
# Bands of the district's apartment sale price over the whole series period (만원 floors), for grouping results.
PRICE_BANDS = ((150000, "15억 원 이상"), (90000, "9억~15억 원"), (60000, "6억~9억 원"), (30000, "3억~6억 원"),
               (0, "3억 원 미만"))
NO_PRICE = "아파트 거래 적음"
PRICE_BAND_ORDER = [label for _, label in PRICE_BANDS] + [NO_PRICE]
# Example homes whose blocks the site shows, so readers see exactly what a person was given.
EXAMPLE_HOMES = (
    {"district": "서울-강남구", "housing_type": "아파트", "tenure": "own", "multi_home": True},
    {"district": "서울-노원구", "housing_type": "다세대주택", "tenure": "monthly", "multi_home": None},
    {"district": "경상북-안동시", "housing_type": "단독주택", "tenure": "own", "multi_home": False},
)


def _read(name: str) -> dict:
    return json.loads((OFFICIAL / name).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def tables() -> dict:
    return {"regions": _read("regions.json")["districts"], "census": _read("census2020_tenure.json")["regions"],
            "ownership": _read("ownership2024.json")["regions"], "survey2024": _read("tenure.json")}


@lru_cache(maxsize=1)
def load_market() -> dict:
    return _read("housing_market.json")


def _collapse(counts: dict) -> dict:
    """Census tenure counts -> the four tenures, smoothed and normalised."""
    four = {"own": counts.get("own", 0.0), "jeonse": counts.get("jeonse", 0.0),
            "monthly": counts.get("monthly_deposit", 0.0) + counts.get("monthly_nodeposit", 0.0) + counts.get("sagulse", 0.0),
            "free": counts.get("free", 0.0)}
    total = sum(four.values()) + SMOOTH * len(four)
    return {k: (v + SMOOTH) / total for k, v in four.items()}


def head_age(person: dict) -> int:
    age = int(person["age"])
    ft = person.get("family_type") or ""
    if ft in GRANDPARENT_HOUSEHOLD:
        return min(age + 50, 85)
    if ft in PARENT_HOUSEHOLD:
        return min(max(age + 28, 40), 85)
    return age


def age_band(age: int, single: bool) -> str:
    if single:
        if age < 20:
            return "20세 미만"
        if age >= 85:
            return "85세 이상"
        lo = age // 5 * 5
        return f"{lo}~{lo + 4}"
    if age < 15:
        return "15세미만"
    if age >= 85:
        return "85세이상"
    lo = age // 5 * 5
    return f"{lo} ~ {lo + 4}세"


def _survey_factors(province_display: str, census_province: dict) -> dict:
    """2024 survey share / 2020 census share per tenure group for a province (renters share one factor)."""
    survey = tables()["survey2024"]
    c = _collapse(census_province["housing"]["계"])
    c_rent = c["jeonse"] + c["monthly"]
    own, rent, free = survey["own"].get(province_display), survey["rent"].get(province_display), survey["free"].get(province_display)
    if own is None:
        return {k: 1.0 for k in TENURES}
    return {"own": own / c["own"], "jeonse": rent / c_rent, "monthly": rent / c_rent, "free": free / c["free"]}


def tenure_probs(person: dict) -> dict:
    t = tables()
    reg = t["regions"][person["district"]]
    district = t["census"][reg["kosis2020"]]
    single = (person.get("family_type") or "") in SINGLE
    by_type = district["housing"].get(CENSUS_HOUSING.get(person["housing_type"], "계")) or district["housing"]["계"]
    ages = district["single_age" if single else "age"]
    by_age = ages.get(age_band(head_age(person), single)) or ages["합계"]
    base = _collapse(district["housing"]["계"])
    p_type, p_age = _collapse(by_type), _collapse(by_age)
    raw = {k: p_type[k] * p_age[k] / base[k] for k in TENURES}
    province = t["census"].get(reg["kosis2020"][:2])
    if province:
        factors = _survey_factors(config.PROVINCE_DISPLAY.get(person["province"], person["province"]), province)
        raw = {k: raw[k] * factors[k] for k in TENURES}
    total = sum(raw.values())
    return {k: round(v / total, 6) for k, v in raw.items()}


def _rng(seed: int, uuid: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}:{uuid}".encode()).hexdigest()[:16], 16))


def assign(person: dict, seed: int = 2026) -> dict:
    """Seeded draw of a tenure, and for owners whether the household owns two or more homes."""
    probs = tenure_probs(person)
    rng = _rng(seed, person["uuid"])
    u, acc, tenure = rng.random(), 0.0, TENURES[-1]
    for k in TENURES:
        acc += probs[k]
        if u < acc:
            tenure = k
            break
    multi = None
    if tenure == "own":
        homes = tables()["ownership"].get(tables()["regions"][person["district"]]["kosis2024"], {}).get("homes_owned", {})
        total = homes.get("총계") or 0
        share = (total - homes.get("1건", total)) / total if total else 0.0
        multi = rng.random() < share
    return {"tenure": tenure, "probs": probs, "multi_home": multi}


def price_band(district: str, market: dict) -> str:
    """The district's apartment price band (median sale over the whole period), or NO_PRICE with too few sales."""
    level = (market.get("levels") or {}).get(district)
    if not level or level["small"] or level["median"] is None:
        return NO_PRICE
    return next(label for floor, label in PRICE_BANDS if level["median"] >= floor)


def examples(measure_id: str, market: dict) -> list[dict]:
    """The blocks EXAMPLE_HOMES would get for a measure, labelled for the site."""
    out = []
    for home in EXAMPLE_HOMES:
        tenure = TENURE_KO[home["tenure"]]
        extra = " · 2채 이상" if home["multi_home"] else " · 1주택" if home["tenure"] == "own" else ""
        out.append({"label": f"{home['district'].replace('-', ' ')} · {home['housing_type']} {tenure}{extra}",
                    "text": housing_block(home, home, measure_id, market)})
    return out


def _money(manwon: float | None) -> str:
    if manwon is None:
        return "–"
    if manwon >= 10000:
        return f"{manwon / 10000:.1f}억 원"
    return f"{manwon:,.0f}만 원"


def period_ko(yms: list[str]) -> str:
    a, b = yms[0], yms[-1]
    if a[:4] == b[:4]:
        return f"{a[:4]}년 {int(a[4:])}~{int(b[4:])}월"
    return f"{a[:4]}년 {int(a[4:])}월~{b[:4]}년 {int(b[4:])}월"


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def housing_block(person: dict, assignment: dict, measure_id: str, market: dict) -> str:
    """Korean text for the Jev state: the assumed tenure, local market facts before the announcement, local
    ownership facts. Cells with too few transactions are left out."""
    district = person["district"]
    place = district.replace("-", " ")
    home_type = person["housing_type"]
    tenure = assignment["tenure"]
    own_line = f"자가({home_type})" + (", 집 2채 이상 보유" if assignment.get("multi_home") else ", 1주택" if tenure == "own" else "")
    lines = ["주거 정보(공식 통계를 바탕으로 정함)",
             f"- 사는 집: {own_line if tenure == 'own' else f'{TENURE_KO[tenure]}({home_type})'}"]
    cell = (market.get("districts", {}).get(district, {}) or {}).get(measure_id, {})
    mtype = MARKET_TYPE.get(home_type, "Apt")
    parts = []
    for t in dict.fromkeys([mtype, "Apt"]):
        c = cell.get(t)
        if not c:
            continue
        tr, rn = c["trade"], c["rent"]
        facts = []
        if not tr["small"]:
            facts.append(f"매매 중위 {_money(tr['median'])}")
            if t == "Apt":
                facts.append(f"15억 원 초과 거래 {_pct(tr['over_15'])}, 25억 원 초과 {_pct(tr['over_25'])}")
        if not rn["small"]:
            if rn["jeonse_median"] is not None:
                facts.append(f"전세 중위 {_money(rn['jeonse_median'])}")
            if rn["monthly_rent_median"] is not None:
                facts.append(f"월세 중위 {_money(rn['monthly_rent_median'])}(보증금 {_money(rn['monthly_deposit_median'])})")
        if facts:
            parts.append(f"{MARKET_TYPE_KO[t]} " + ", ".join(facts))
    if parts:
        window = market["windows"][measure_id]
        lines.append(f"- {place} 실거래({period_ko(window)}): " + " / ".join(parts))
    own = tables()["ownership"].get(tables()["regions"][district]["kosis2024"], {})
    homes, assets = own.get("homes_owned", {}), own.get("asset_value", {})
    if homes.get("총계") and assets.get("총계"):
        multi = (homes["총계"] - homes.get("1건", 0)) / homes["총계"]
        high = assets.get("12억 초과", 0) / assets["총계"]
        lines.append(f"- {place}에서 집을 가진 가구 중 2채 이상 {_pct(multi)}, 공시가격 기준 12억 원 초과 {_pct(high)}(2024)")
    return "\n".join(lines)


# Same shape as the housing block with the facts left out, so a difference from it is the facts' effect.
PLACEBO = ("주거 정보(공식 통계를 바탕으로 정함)\n"
           "- 사는 집: 인물 설명에 적힌 주거 형태와 같음\n"
           "- 사는 곳의 주택 거래 정보: 이 조건에서는 넣지 않음\n"
           "- 사는 곳의 주택 소유 정보: 이 조건에서는 넣지 않음")
