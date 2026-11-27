"""Compile the raw KOSIS downloads (scripts/fetch_persona_context.py) into series/official/persona_context.json,
keyed by the persona DB's districts ("서울-송파구") and provinces ("서울").

  ../.venv/bin/python scripts/build_persona_context.py

District tables are matched by name inside a province (KOSIS codes differ between tables and years); a district
missing from a table falls back to its city ("수원시 장안구" -> "수원시") and then to the province. Every fallback is
listed in the output so the assignment can say which level a number came from.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
RAW = ENGINE.parent / "data" / "official" / "kosis" / "context"
OFFICIAL = ENGINE / "series" / "official"

PROVINCES = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
             "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
             "강원도": "강원", "충청북도": "충청북", "충청남도": "충청남", "전북특별자치도": "전북", "전라북도": "전북",
             "전라남도": "전라남", "경상북도": "경상북", "경상남도": "경상남", "제주특별자치도": "제주"}
METRO = {"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종"}
# lawd (행정) code prefix -> persona province, for the resident-population table
LAWD_PROVINCE = {"11": "서울", "26": "부산", "27": "대구", "28": "인천", "29": "광주", "30": "대전", "31": "울산",
                 "36": "세종", "41": "경기", "42": "강원", "51": "강원", "43": "충청북", "44": "충청남", "45": "전북",
                 "52": "전북", "46": "전라남", "47": "경상북", "48": "경상남", "50": "제주"}
COMMUTE_MODES = {"걸어서": "walk", "자전거": "bike", "승용차승합차(벤)": "car", "트럭": "car", "시내좌석마을버스": "bus",
                 "통근통학차량": "shuttle", "고속시외버스": "intercity_bus", "전철지하철": "subway", "기차": "rail",
                 "택시": "taxi", "기타": "other", "복합수단": "multi"}
RELIGIONS = {"불교": "buddhist", "기독교(개신교)": "protestant", "기독교(천주교)": "catholic", "종교없음-계": "none"}
RELIGION_OTHER = ("원불교", "유교", "천도교", "대순진리회", "대종교", "기타")
INCOME_BANDS = {"1000만원 미만": "lt10", "1000~3000만원 미만": "10_30", "3000~5000만원 미만": "30_50",
                "5000~7000만원 미만": "50_70", "7000~10000만원 미만": "70_100", "10000만원 이상": "ge100"}


def raw(name: str) -> list[dict]:
    return json.loads((RAW / f"{name}.json").read_text(encoding="utf-8"))


def num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def percent(x, digits=5):
    value = num(x)
    return round(value / 100, digits) if value is not None else None


def known_sum(values):
    """A missing summand makes the total unknown, including an entirely absent series."""
    values = list(values)
    return sum(values) if values and all(v is not None for v in values) else None


def age5(label: str) -> str | None:
    """'40 ~ 44세' / '40 - 44세' / '40~44세' -> '40'; '85세이상'/'100+' -> lower bound; totals -> None."""
    m = re.match(r"^\s*(\d+)\s*(?:~|-)\s*(\d+)\s*세?\s*$", label or "")
    if m and int(m.group(2)) - int(m.group(1)) == 4:
        return m.group(1)
    m = re.match(r"^\s*(\d+)\s*(?:세\s*이상|\+)\s*$", label or "")
    return m.group(1) if m else None


def districts() -> dict:
    return json.loads((OFFICIAL / "regions.json").read_text(encoding="utf-8"))["districts"]


def name_index(rows: list[dict]) -> dict:
    """{(province, name): code} from a KOSIS table listed province -> city -> 구 in code order."""
    index, province, city = {}, None, None
    for code, name in sorted({(r["C1"], r["C1_NM"]) for r in rows}):
        name = name.strip()
        if name in PROVINCES:
            province, city = PROVINCES[name], None
            index[(province, "")] = code
            continue
        if province is None:
            continue
        clean = name.replace("통합", "")
        if province not in METRO and clean.endswith("구") and city:
            index[(province, f"{city} {clean}")] = code
            continue
        if clean.endswith("시"):
            city = clean
        index.setdefault((province, clean), code)
    return index


def resolve(index: dict, district: str) -> tuple[str | None, str]:
    """(code, level) for a persona district, level in district/city/province/missing."""
    province, name = district.split("-", 1)
    if (province, name) in index:
        return index[(province, name)], "district"
    if " " in name and (province, name.split(" ")[0]) in index:
        return index[(province, name.split(" ")[0])], "city"
    if (province, "") in index:
        return index[(province, "")], "province"
    return None, "missing"


def population() -> dict:
    """{district: {sex: {age5: n}}} from resident registration (Dec 2025). Districts whose 2026 codes are newer than
    the data are matched by name on the old codes."""
    rows = raw("population")
    by_code: dict = defaultdict(lambda: {"남자": defaultdict(float), "여자": defaultdict(float)})
    names = {}
    for r in rows:
        a, v = age5(r["C2_NM"]), num(r["DT"])
        names[r["C1"]] = r["C1_NM"].strip()
        sex = {"남자인구수": "남자", "여자인구수": "여자"}.get(r["ITM_NM"])
        if a and sex and v is not None:
            by_code[r["C1"]][sex][a] += v
    by_name = {(LAWD_PROVINCE.get(c[:2]), n): c for c, n in names.items()}
    out, fallback = {}, []
    for district, reg in districts().items():
        codes = [c["code"] for c in reg["lawd"] if c["code"] in by_code]
        if not codes:
            province, name = district.split("-", 1)
            code = by_name.get((province, name.split(" ")[-1])) or by_name.get((province, name))
            codes = [code] if code else []
            fallback.append(district)
        if not codes:
            continue
        agg = {"남자": defaultdict(float), "여자": defaultdict(float)}
        for c in codes:
            for sex in agg:
                for a, v in by_code[c][sex].items():
                    agg[sex][a] += v
        out[district] = {sex: dict(v) for sex, v in agg.items()}
    return {"by_district": out, "name_matched": fallback}


def disability(pop: dict) -> dict:
    rows = raw("disability")
    index = name_index(rows)
    counts: dict = defaultdict(lambda: {"남자": {}, "여자": {}})
    for r in rows:
        a, v = age5(r["C2_NM"]), num(r["DT"])
        sex = {"장애인 인구_남자": "남자", "장애인 인구_여자": "여자"}.get(r["ITM_NM"])
        if a and sex and v is not None:
            counts[r["C1"]][sex][a] = v
    out, levels = {}, defaultdict(list)
    for district in districts():
        code, level = resolve(index, district)
        levels[level].append(district)
        p = pop["by_district"].get(district)
        if code is None or p is None or level != "district":
            continue  # rates need a matching denominator; coarser fallbacks would mix areas
        out[district] = {sex: {a: round(min(1.0, n / p[sex][a]), 5) for a, n in counts[code][sex].items()
                               if p[sex].get(a)} for sex in ("남자", "여자")}
    return {"rate": out, "levels": {k: len(v) for k, v in levels.items()},
            "not_district": sorted(levels["city"] + levels["province"] + levels["missing"])}


def livelihood(pop: dict) -> dict:
    """{province: {sex: {age5: rate}}}: basic livelihood (general) recipients / resident population."""
    rows = raw("livelihood")
    counts: dict = defaultdict(lambda: {"남자": defaultdict(float), "여자": defaultdict(float)})
    for r in rows:
        a, v = age5(r["C3_NM"]), num(r["DT"])
        province = PROVINCES.get(r["C1_NM"].strip())
        if a and province and r["C2_NM"] in ("남자", "여자") and v is not None:
            counts[province][r["C2_NM"]][a] += v
    denom: dict = defaultdict(lambda: {"남자": defaultdict(float), "여자": defaultdict(float)})
    for district, p in pop["by_district"].items():
        for sex in p:
            for a, v in p[sex].items():
                denom[district.split("-")[0]][sex][a] += v
    # 85+ bands collapse to '85' in both tables
    out = {}
    for province, c in counts.items():
        out[province] = {}
        for sex in c:
            d = defaultdict(float)
            n = defaultdict(float)
            for a, v in denom[province][sex].items():
                d[str(min(int(a), 85))] += v
            for a, v in c[sex].items():
                n[str(min(int(a), 85))] += v
            out[province][sex] = {a: round(n[a] / d[a], 5) for a in n if d.get(a)}
    return out


def religion() -> dict:
    """{province: {sex: {age5_in_2015: shares}}} from the 2015 census (the last census asking religion)."""
    out: dict = defaultdict(lambda: defaultdict(dict))
    cells: dict = defaultdict(dict)
    for r in raw("religion"):
        a, v = age5(r["C3_NM"]), num(r["DT"])
        province = PROVINCES.get(r["C1_NM"].strip())
        if a and province and r["C2_NM"] in ("남자", "여자") and v is not None:
            cells[(province, r["C2_NM"], a)][r["ITM_NM"]] = v
    for (province, sex, a), c in cells.items():
        shares = {k: c.get(src) for src, k in RELIGIONS.items()}
        shares["other"] = known_sum(c.get(x) for x in RELIGION_OTHER)
        total = known_sum(shares.values())
        if total:
            out[province][sex][a] = {k: round(v / total, 5) for k, v in shares.items()}
        else:
            out[province][sex][a] = {k: None for k in shares}
    return {p: dict(v) for p, v in out.items()}


def commute() -> dict:
    """{district: {sex: {age5: {mode: share}}}} for commuters to work (2020 census, 통근 only)."""
    reg = districts()
    by_code = {v["kosis2020"]: k for k, v in reg.items()}
    cells: dict = defaultdict(dict)
    for r in raw("commute"):
        if r["C4_NM"] != "통근" or r["C2_NM"] not in ("남자", "여자"):
            continue
        district = by_code.get(r["C1"])
        mode = COMMUTE_MODES.get(r["ITM_NM"])
        a = age5(r["C3_NM"]) or ("75" if r["C3_NM"] == "75세 이상" else None)
        v = num(r["DT"])
        if district and mode and a and v is not None:
            key = (district, r["C2_NM"], a)
            cells[key][mode] = cells[key].get(mode, 0.0) + v
    out: dict = defaultdict(lambda: defaultdict(dict))
    for (district, sex, a), c in cells.items():
        total = sum(c.values())
        if total >= 20:  # tiny cells are noise; the assignment falls back to the district's all-ages row
            out[district][sex][a] = {k: round(v / total, 4) for k, v in c.items() if v}
        allages = out[district][sex].setdefault("all", defaultdict(float))
        for k, v in c.items():
            allages[k] += v
    for district in out:
        for sex in out[district]:
            c = out[district][sex]["all"]
            total = sum(c.values())
            out[district][sex]["all"] = {k: round(v / total, 4) for k, v in c.items() if v} if total else {}
    return {d: {s: dict(v) for s, v in x.items()} for d, x in out.items()}


def district_rate(name: str, item: str) -> dict:
    rows = [r for r in raw(name) if r.get("ITM_ID", "") == item or r.get("ITM_NM") == item]
    index = name_index(rows)
    values = {r["C1"]: num(r["DT"]) for r in rows}
    out, levels = {}, defaultdict(int)
    for district in districts():
        code, level = resolve(index, district)
        levels[level] += 1
        if code and values.get(code) is not None:
            out[district] = {"rate": round(values[code] / 100, 4), "level": level}
    return {"by_district": out, "levels": dict(levels)}


def knhanes(name: str) -> dict:
    """{sex: {age10: rate}} national shape (KNHANES), sex in 남자/여자, age10 in 19/30/40/50/60/70."""
    out: dict = defaultdict(dict)
    for r in raw(name):
        if r["ITM_NM"] != "분율" or r["C1_NM"] not in ("남자", "여자"):
            continue
        m = re.match(r"^(\d+)-\d+세$|^(70)세이상$", r["C2_NM"])
        if m:
            out[r["C1_NM"]].setdefault(m.group(1) or m.group(2), round(float(r["DT"]) / 100, 4))
    return dict(out)


def employment() -> dict:
    """{province: {sex: {age5: shares}}} employment status of workers (2020 census); ages 70+ share one row."""
    keys = {"임금 근로자": "wage", "고용원이 없는 자영업자": "self_alone", "고용원이 있는 자영업자": "employer",
            "무급 가족 종사자": "family"}
    cells: dict = defaultdict(dict)
    for r in raw("employment"):
        province = PROVINCES.get(r["C1_NM"].strip())
        a = age5(r["C3_NM"].replace("-", "~")) or ("70" if r["C3_NM"] == "70세 이상" else None)
        v = num(r["DT"])
        if province and a and r["C2_NM"] in ("남자", "여자") and r["ITM_NM"] in keys and v is not None:
            cells[(province, r["C2_NM"], a)][keys[r["ITM_NM"]]] = v
    out: dict = defaultdict(lambda: defaultdict(dict))
    for (province, sex, a), c in cells.items():
        total = sum(c.values())
        if total:
            out[province][sex][a] = {k: round(v / total, 4) for k, v in c.items()}
    return {p: dict(v) for p, v in out.items()}


def nps_oldage(pop: dict) -> dict:
    """{province: {sex: {age5: rate}}} National Pension old-age pension recipients / residents, ages 60+ (80 = 80+)."""
    short = {"강원": "강원", "충북": "충청북", "충남": "충청남", "전북": "전북", "전남": "전라남", "경북": "경상북",
             "경남": "경상남"}
    counts: dict = defaultdict(lambda: defaultdict(float))
    for r in raw("nps_oldage"):
        m = re.match(r"^(\d+)세", r["C2_NM"])
        v = num(r["DT"])
        if not m or r["C3_NM"] not in ("남자", "여자") or v is None or int(m.group(1)) < 60:
            continue
        province = short.get(r["C1_NM"], r["C1_NM"])
        counts[(province, r["C3_NM"])][str(min(int(m.group(1)) // 5 * 5, 80))] += v
    denom: dict = defaultdict(lambda: defaultdict(float))
    for district, p in pop["by_district"].items():
        for sex in p:
            for a, v in p[sex].items():
                if int(a) >= 60:
                    denom[(district.split("-")[0], sex)][str(min(int(a), 80))] += v
    out: dict = defaultdict(dict)
    for (province, sex), c in counts.items():
        d = denom.get((province, sex), {})
        out[province][sex] = {a: round(min(1.0, v / d[a]), 4) for a, v in c.items() if d.get(a)}
    return dict(out)


def basic_pension() -> dict:
    """{age group: receipt rate} for 기초·장애인연금, 2024 pension statistics (65+)."""
    groups = {"65~69세": "65", "70~74세": "70", "75~79세": "75", "80세 이상": "80"}
    return {groups[r["C2_NM"]]: round(float(r["DT"]) / 100, 4) for r in raw("pension_65")
            if r["ITM_NM"] == "수급률" and r["C3_NM"] == "기초ㆍ장애인연금" and r["C2_NM"] in groups}


def networth() -> dict:
    """Net worth quintiles: mean net worth per quintile, P(income band | quintile), and published mean net worth by
    head age, tenure and province for matching."""
    means = {r["C2_NM"][-3:-2]: round(float(r["DT"])) for r in raw("networth_quintile")
             if r["C1_NM"] == "전체" and r["C3_NM"] == "순자산액" and r["ITM_NM"] == "전가구 평균"
             and r["C2_NM"].startswith("순자산") and r["C2_NM"][-2:] == "분위"}

    def mean_by(name: str) -> dict:
        return {r["C2_NM"]: round(float(r["DT"])) for r in raw(name)
                if r["C1_NM"] == "전체" and r["C3_NM"] == "순자산액" and r["ITM_NM"] == "전가구 평균"}

    income_given_q = {}
    for r in raw("income_band"):
        m = re.match(r"^\(순자산\) (\d)분위$", r["C1_NM"])
        band = INCOME_BANDS.get(r["C2_NM"])
        if m and band:
            income_given_q.setdefault(m.group(1), {})[band] = percent(r["DT"])
    for row in income_given_q.values():
        for band in INCOME_BANDS.values():
            row.setdefault(band, None)
    return {"quintile_mean": means, "income_given_quintile": income_given_q,
            "mean_by_age": mean_by("finance_age"), "mean_by_tenure": mean_by("finance_tenure"),
            "mean_by_region": mean_by("finance_region")}


def work_extra() -> dict:
    dual = {r["C1_NM"].replace(" ", ""): round(float(r["DT"]) / 100, 4) for r in raw("dual_earner")
            if "비율" in r["ITM_NM"]}
    wage, nonreg = defaultdict(dict), defaultdict(dict)
    for r in raw("contract"):
        if r["C1_NM"] in ("남자", "여자"):
            target = wage if r["ITM_NM"] == "임금근로자" else nonreg if r["ITM_NM"] == "비정규직" else None
            if target is not None:
                target[r["C1_NM"]][r["C2_NM"].replace(" ", "")] = float(r["DT"])
    contract = {sex: {a: round(nonreg[sex][a] / wage[sex][a], 4) for a in wage[sex] if wage[sex][a]} for sex in wage}
    return {"dual_earner_by_head_age": dual, "nonregular_by_sex_age": contract,
            "contract_period": raw("contract")[0]["PRD_DE"]}


def digital() -> dict:
    """'Can find what I need online' (4-level) for adults 20-59 and 60-69, and the 2025 digital divide survey's
    competence index for older adults (general public = 100) by age, sex and monthly household income."""
    find = defaultdict(dict)
    for r in raw("digital_use"):
        if r["C2_NM"].startswith("온라인상에서 필요한") and r["C3_NM"] != "4점만점":
            find[r["C1_NM"]][r["C3_NM"]] = round(float(r["DT"]) / 100, 4)
    gap = {r["C1_NM"]: float(r["DT"]) for r in raw("digital_gap_elderly") if r["ITM_NM"] == "역량"}
    return {"find_online": {"20-59": find["성인(만20~59세)"], "60-69": find["60대(만60~69세)"]}, "elderly_competence": gap}


def elder() -> dict:
    """노인실태조사 2023 (65+): functional limitation (none / IADL only / ADL too) and care receipt among the limited,
    each by sex, age, household type and education."""
    def table(name: str, items: dict) -> dict:
        out = defaultdict(dict)
        for r in raw(name):
            k = items.get(r["C2_NM"].strip())
            v = num(r["DT"])
            if k and v is not None:
                out[r["C1_NM"].strip()][k] = round(v / 100, 4)
        return dict(out)
    return {"function": table("elder_function", {"기능제한 없음": "none", "IADL만 제한": "iadl", "ADL도 제한": "adl"}),
            "care": table("elder_care", {"돌봄 수급률": "yes"})}


def finance() -> dict:
    """Household finance survey 2025: income-band shares and debt/car holding rates by household trait."""
    income: dict = defaultdict(dict)
    for r in raw("income_band"):
        band = INCOME_BANDS.get(r["C2_NM"])
        if band:
            income[r["C1_NM"]][band] = percent(r["DT"])
    for row in income.values():  # unpublished is unknown, never a zero-share raking constraint
        for band in INCOME_BANDS.values():
            row.setdefault(band, None)
    debt = {r["C1_NM"]: round(float(r["DT"]) / 100, 4) for r in raw("debt_traits")
            if r["ITM_ID"] == "T03" and r["C2_NM"] == "부채"}

    def holding(name: str, item: str) -> dict:
        return {r["C2_NM"]: round(float(r["DT"]) / 100, 4) for r in raw(name)
                if r["C1_NM"] == "전체" and r["C3_NM"] == item and r["ITM_NM"] == "보유가구 비율"}

    def shares(name: str) -> dict:
        return {r["C2_NM"]: round(float(r["DT"]) / 100, 4) for r in raw(name)
                if r["C1_NM"] == "전체" and r["C3_NM"] == "가구분포" and r["ITM_NM"] == "전가구 평균"}

    def mean(name: str, item: str) -> dict:
        return {r["C2_NM"]: round(float(r["DT"])) for r in raw(name)
                if r["C1_NM"] == "전체" and r["C3_NM"] == item and r["ITM_NM"] == "전가구 평균"}

    return {
        "income_band": dict(income), "debt_holding": debt,
        "car_by_age": holding("finance_age", "자동차"), "car_by_tenure": holding("finance_tenure", "자동차"),
        "car_by_size": holding("finance_size", "자동차"), "debt_by_tenure": holding("finance_tenure", "부채"),
        "share_by_status": shares("finance_status"), "share_by_size": shares("finance_size"),
        "share_by_tenure": shares("finance_tenure"),
        # held out of the assignment, used only to check it
        "mean_income_by_region": mean("finance_region", "경상소득(전년도)"),
        "mean_income_by_tenure": mean("finance_tenure", "경상소득(전년도)"),
    }


def one_way(name: str, yes: str) -> dict:
    """{category: share answering `yes`} from a one-way survey table (first occurrence of a repeated label)."""
    out: dict = {}
    for r in raw(name):
        v = num(r["DT"])
        if r["ITM_NM"] == yes and v is not None:
            out.setdefault(r["C1_NM"].strip(), round(v / 100, 4))
    return out


def survey_share(name: str, parts: list[dict], total: str = "전체", drop: tuple = ()) -> dict:
    """{category label: share} from a multi-dimensional survey table. Each part selects rows (`where`), labels them by
    one field (`by`) and sums the `yes` answers (field -> accepted values); the first occurrence of a label wins."""
    out: dict = {}
    rows = raw(name)
    for part in parts:
        sums: dict = {}
        for r in rows:
            if any(r.get(k, "").strip() != v for k, v in part.get("where", {}).items()):
                continue
            label = r[part["by"]].strip()
            if label in drop or any(r.get(k, "").strip() not in vals for k, vals in part["yes"].items()):
                continue
            v = num(r["DT"])
            if v is not None:
                sums[label] = sums.get(label, 0) + v
        for label, v in sums.items():
            out.setdefault("전체" if label == total else label, round(v / 100, 4))
    return out


C1, C2, C3 = "C1_NM", "C2_NM", "C3_NM"
LAST_YEAR = ["① 지난 1년 동안 한 적이 있다"]
MEMBER_NOW = ["소속되어 있지만 활동은 안 한다", "소속되어 적극적으로 활동한다", "소속되어 있지만 적극적으로 활동하지 않는다"]
# Binary survey attributes: (raw table, parts, options). Labels are matched to panel members by pp.survey_match.
SURVEY_SHARES = {
    "petition": ("civic_voice", [{"by": C1, "where": {C2: "서명운동 참여"}, "yes": {C3: LAST_YEAR}}], {}),
    "online_voice": ("civic_voice", [{"by": C1, "where": {C2: "온라인 의견 피력"}, "yes": {C3: LAST_YEAR}}], {}),
    "contacted_official": ("civic_voice", [{"by": C1, "where": {C2: "공무원·정치인에 민원 전달"}, "yes": {C3: LAST_YEAR}}], {}),
    "voted_general": ("civic_vote", [{"by": C1, "where": {C2: "제22대 국회의원 선거"}, "yes": {C3: ["참여했다"]}}], {}),
    "community_group": ("civic_groups", [{"by": C1, "where": {C2: "지역사회 공공모임"}, "yes": {C3: MEMBER_NOW}}], {}),
    "lonely": ("civic_isolation", [{"by": C1, "where": {C2: "외롭다고 느끼는 정도"},
                                    "yes": {C3: ["③ 약간 그렇다", "④ 매우 그렇다"]}}], {}),
    "volunteer": ("volunteer", [{"by": C1, "yes": {"ITM_NM": ["예"]}}], {}),
    "travel_abroad": ("travel_abroad", [{"by": C1, "yes": {"ITM_NM": ["경험"]}}], {}),
    "breakfast_skip": ("breakfast_skip", [{"by": C2, "where": {C1: "전체"}, "yes": {"ITM_NM": ["분율"]}},
                                          {"by": C1, "where": {C2: "19세이상"}, "yes": {"ITM_NM": ["분율"]}}],
                       {"total": "19세이상", "drop": ("1세이상", "1세이상(표준화)", "19세이상(표준화)")}),
    "private_insurance": ("private_insurance", [{"by": C1, "yes": {"ITM_NM": ["전체 가구원 대비"]}}], {}),
    "unmet_care": ("unmet_care", [{"by": C1, "where": {C2: "전체"}, "yes": {"ITM_NM": ["분율"]}},
                                  {"by": C2, "where": {C1: "전체"}, "yes": {"ITM_NM": ["분율"]}}], {}),
    "night_work": ("night_work", [{"by": C2, "yes": {C1: ["1~5일", "5일 초과"]}}], {}),
    "shift_work": ("shift_work", [{"by": C2, "yes": {C1: ["그렇다"]}}], {}),
    "sleep_trouble": ("sleep_trouble", [{"by": C2, "yes": {C1: ["매일", "한 주에 여러번"]}}], {}),
    "kiosk_hard": ("kiosk", [{"by": C1, "yes": {"ITM_NM": ["전혀 그렇지 않다", "그렇지 않다"]}}], {}),
    "senior_job": ("senior_job", [{"by": C1, "yes": {C2: ["현재 참여 중"]}}], {}),
    "union": ("union_pension", [{"by": C1, "where": {C2: "전직종"}, "yes": {"ITM_NM": ["노조가입"]}}],
              {"total": "전체근로자(특수형태제외)"}),
    "protest": ("civic_voice", [{"by": C1, "where": {C2: "시위·집회 참여"}, "yes": {C3: LAST_YEAR}}], {}),
    "boycott": ("civic_voice", [{"by": C1, "where": {C2: "불매운동 참여"}, "yes": {C3: LAST_YEAR}}], {}),
    "youth_no_help_sick": ("youth_help", [{"by": C1, "where": {C2: "본인 또는 가족이 아플 때"},
                                           "yes": {C3: ["어떤 사람/기관도 도움받을 데가 없음"]}}], {}),
    "youth_mental_unmet": ("youth_mental_unmet", [{"by": C1, "yes": {"ITM_NM": ["정신건강 미충족 의료 경험"]}}], {}),
    "youth_move": ("youth_move", [{"by": C1, "yes": {C2: ["다른 지역으로 이사하고 싶다"]}}], {}),
    "long_hours": ("work_hours", [{"by": C2, "yes": {C1: ["주 50시간 이상"]}}], {}),
    "worker_care": ("worker_care", [{"by": C2, "yes": {C1: ["매일", "한 주에 여러번"]}}], {}),
    "platform_self": ("platform_self", [{"by": C2, "yes": {C1: ["그렇다"]}}], {}),
    "retirement_pension": ("union_pension", [{"by": C1, "where": {C2: "전직종"}, "yes": {"ITM_NM": ["퇴직연금"]}}],
                           {"total": "전체근로자(특수형태제외)"}),
}
SURVEY_SOURCES = {
    "civic": "한국행정연구원 2025 사회통합실태조사(의견 피력·선거 투표·사회단체·사회적 고립감), KOSIS 417 DT_417001_0027/0028/0021/0035",
    "volunteer": "문화체육관광부 2025 국민여가활동조사 계열 자원봉사 참여 경험, KOSIS 113 DT_113_STBL_1028450",
    "travel_abroad": "문화체육관광부 2025 해외여행 경험률, KOSIS 113 DT_113_STBL_1029566",
    "breakfast_skip": "질병관리청 2024 국민건강영양조사 아침식사 결식률(19세 이상), KOSIS 177 DT_11702_N033",
    "medical": "한국보건사회연구원·국민건강보험공단 2023 한국의료패널(민간의료보험 가입·병의원 미충족 의료), KOSIS 331 DT_920012N_1072/2056",
    "worklife": "안전보건공단 2023 제7차 근로환경조사(밤 근무·교대근무·입면 곤란), KOSIS 380 DT_380002_A0561/A0815/A0971_7TH",
    "kiosk": "2025 디지털 역량(키오스크 이용) 조사, KOSIS 164 DT_164004_2025273",
    "senior_job": "보건복지부 2023 노인실태조사 노인일자리사업 참여, KOSIS 117 DT_117071_G004",
    "youth": "국무조정실 2024 청년 삶 실태조사(19~34세: 아플 때 도움받을 곳, 정신건강 미충족 의료, 타 시도 이주 의향), KOSIS 170 DT_170002_F001/C017/B034",
    "worklife2": "안전보건공단 2023 제7차 근로환경조사(주업 근무시간·가족 돌봄·자영업 플랫폼), KOSIS 380 DT_380002_A08401/A1002/A0044_7TH",
    "history_income_mobility": "국가데이터처 소득이동통계 2018~2024(성·연령·분위 5x5 이동, 1·5분위 지속), KOSIS 101 DT_IMEMIA001/ID001/ID002",
    "history_income_change": "국가데이터처 소득이동통계 2018~2024 절대적 소득이동성(전년 대비 소득 금액 변화 7범주, 성·전년연령·전년분위), KOSIS 101 DT_IMEMIC001",
    "history_wage_level": "통계청 일자리행정통계 임금근로일자리 소득 2016~2024(성·연령대별 월평균·중위소득), KOSIS 101 DT_1EP_2010",
    "history_employment": "통계청 경제활동인구조사 2017~2025 성·연령별 고용률, KOSIS 101 DT_1DA7012S",
    "history_migration": "통계청 인구이동통계 2017~2025 전출지/전입지(시도)별 이동자수, 시도간 전입 성·연령별, KOSIS 101 DT_1B26003_A01/DT_1B26001_A04",
    "history_marriage": "통계청 인구동향 2017~2025 성·연령별 혼인율(천명당), KOSIS 101 DT_1B83A15",
    "history_divorce": "통계청 인구동향 2017~2025 성·연령별 이혼율(천명당), KOSIS 101 DT_1B85009",
    "history_repeat_movers": "통계청 2005 인구주택총조사 5년 전 거주지(다른 시도) ÷ 2001~2005 인구이동통계 시도간 전입(성·연령) — 반복 이주 성향 보정용, KOSIS 101 DT_1MI0501/DT_1B26001_A04",
    "life_table": "통계청 2024 간이생명표(5세별) 사망확률 → 1년 확률, KOSIS 101 DT_1B41",
    "history_smoking": "질병관리청 지역사회건강조사 2018~2025 시군구 현재흡연율(조율), KOSIS 177 DT_H_SM",
    "driving_license": "경찰청 2024 운전면허 소지자(연령·성·지역) ÷ 2025-12 주민등록인구(20세 이상), KOSIS 132 DT_13201_A002/A004/A005",
    "union_pension": "고용노동부 2025 고용형태별 근로실태조사(노조 가입·퇴직연금 가입, 특수형태 제외), KOSIS 118 DT_118N_LCE310",
}


LICENSE_REGION = {"충청북": "충북", "충청남": "충남", "전라남": "전남", "경상북": "경북", "경상남": "경남"}


def driving_license(pop: dict) -> dict:
    """Share of residents aged 20+ holding a driving licence, by 5-year age, sex and 시도: licence holders (경찰청,
    any class) over the resident population. Holders aged 16-19 are left out of every numerator."""
    nat = {"남자": defaultdict(float), "여자": defaultdict(float)}
    prov: dict = defaultdict(float)
    for district, by_sex in pop["by_district"].items():
        for sex, ages in by_sex.items():
            for a, v in ages.items():
                if int(a) >= 20:
                    nat[sex][a] += v
                    prov[LICENSE_REGION.get(district.split("-")[0], district.split("-")[0])] += v
    by_age: dict = defaultdict(float)
    missing_ages = set()
    for r in raw("license_age"):
        m = re.match(r"(\d+)세", r["C1_NM"])
        v = num(r["DT"])
        if r["C2_NM"].strip() == "총계" and m and int(m.group(1)) >= 20:
            band = min(85, int(m.group(1)) // 5 * 5)
            if v is None:
                missing_ages.add(band)
            else:
                by_age[band] += v
    pop_age: dict = defaultdict(float)
    for sex in nat:
        for a, v in nat[sex].items():
            pop_age[min(85, int(a))] += v
    teen = known_sum(num(r["DT"]) for r in raw("license_age") if r["C2_NM"].strip() == "총계"
               and re.fullmatch(r"1[6-9]세", r["C1_NM"].strip()))
    out = {"전체": round(sum(by_age.values()) / sum(pop_age.values()), 4) if not missing_ages else None}
    for a in sorted(set(by_age) | missing_ages):
        out[f"{a}세 이상" if a == 85 else f"{a}-{a + 4}세"] = round(min(0.99, by_age[a] / pop_age[a]), 4) if a not in missing_ages else None
    share_adult = sum(by_age.values()) / (sum(by_age.values()) + teen) if teen is not None and not missing_ages else None
    for r in raw("license_sex"):
        if r["C1_NM"].strip() == "총계" and r["C2_NM"].strip() in nat:
            sex = r["C2_NM"].strip()
            value = num(r["DT"])
            out[sex] = round(min(0.99, value * share_adult / sum(nat[sex].values())), 4) if value is not None and share_adult is not None else None
    region: dict = defaultdict(list)
    for r in raw("license_region"):
        name = r["C2_NM"].strip()
        if r["C1_NM"].strip() == "총계" and name != "계":
            region["경기" if name.startswith("경기") else name].append(num(r["DT"]))
    for name, values in region.items():
        v = known_sum(values)
        if prov.get(name):
            out[name] = round(min(0.99, v * share_adult / prov[name]), 4) if v is not None and share_adult is not None else None
    return out


MOBILITY_AGES = ("19~39세", "40~64세", "65세 이상")


def income_mobility() -> dict:
    """소득이동통계 by transition year (t-1 -> t), sex and prior-year age group: prior and current quintile shares,
    the 5x5 joint shares, up/stay/down, plus bottom/top quintile persistence. Shares are of each group's two-year
    earners (personal labour + business income)."""
    out: dict = {}
    for r in raw("mobility_joint"):
        sex, age, prior = r["C1_NM"].strip(), r["C2_NM"].strip(), r["C3_NM"].strip()
        if age not in MOBILITY_AGES and age != "계":
            continue
        v = num(r["DT"])
        cell = out.setdefault(r["PRD_DE"], {}).setdefault(sex, {}).setdefault(age, {
            "prior": [None] * 5, "joint": [[None] * 5 for _ in range(5)], "direction": {}})
        m = re.search(r"(\d)분위", prior)
        item = r["ITM_ID"]
        if m:
            i = int(m.group(1)) - 1
            if item == "T10":
                cell["prior"][i] = percent(v, 6)
            elif item in ("T11", "T12", "T13", "T14", "T15"):
                cell["joint"][i][int(item[-1]) - 1] = percent(v, 6)
        elif item in ("T21", "T22", "T23"):
            cell["direction"][{"T21": "up", "T22": "stay", "T23": "down"}[item]] = percent(v, 6)
    for by_sex in out.values():
        for by_age in by_sex.values():
            for cell in by_age.values():
                totals = [known_sum(row[j] for row in cell["joint"]) for j in range(5)]
                cell["current"] = [round(v, 6) if v is not None else None for v in totals]
    persist = {}
    for name, key in (("mobility_low", "q1"), ("mobility_high", "q5")):
        for r in raw(name):
            v = num(r["DT"])
            if v is None:
                continue
            d = persist.setdefault(key, {"stay": {}, "since_2017": {}})
            if r["ITM_ID"] == "T10":
                d["stay"][r["PRD_DE"]] = round(v / 100, 6)
            elif r["ITM_ID"].startswith("T11") and len(r["ITM_ID"]) == 4:
                d["since_2017"].setdefault(r["PRD_DE"], {})[int(r["ITM_ID"][-1])] = round(v / 100, 6)
    return {"by_year": out, "persistence": persist}


INCOME_CHANGE_CATS = {"변화 없음": "same", "소득 감소: 0% 초과 10% 미만 감소": "down_0_10",
                      "소득 감소: 10% 이상 50% 미만 감소": "down_10_50", "소득 감소: 50% 이상 감소": "down_50",
                      "소득 증가: 0% 초과 10% 미만 증가": "up_0_10", "소득 증가: 10% 이상 50% 미만 증가": "up_10_50",
                      "소득 증가: 50% 이상 증가": "up_50"}


def income_change() -> dict:
    """소득이동통계 absolute mobility: {year: {sex: {prior age group: {prior quintile 1-5: {category: share}}}}},
    shares of each cell's two-year earners."""
    out: dict = {}
    for r in raw("income_change"):
        sex, age, prior = r["C1_NM"].strip(), r["C2_NM"].strip(), r["C3_NM"].strip()
        cat = INCOME_CHANGE_CATS.get(r["ITM_NM"].strip())
        m = re.search(r"(\d)분위", prior)
        if age not in MOBILITY_AGES or sex == "계" or not cat or not m:
            continue
        v = num(r["DT"])
        if v is not None:
            out.setdefault(r["PRD_DE"], {}).setdefault(sex, {}).setdefault(age, {}).setdefault(m.group(1), {})[cat] = round(v / 100, 6)
    return out


def wage_level() -> dict:
    """임금근로일자리 소득: {year: {sex: {age band: {"mean", "median"}}}} monthly 만원; bands are the 10-year ones."""
    out: dict = {}
    for r in raw("wage_level"):
        sex, band = r["C1_NM"].strip(), r["C2_NM"].strip().replace(" ", "")
        if sex == "총 계" or band in ("총계", "19세이하") or "~" not in band and band != "70세이상":
            continue
        a = int(band[:2])
        b = 999 if band.endswith("이상") else int(band.split("~")[1].rstrip("세"))
        if b - a != 9 and band != "70세이상":  # keep 20~29, 30~39, ... 60~69, 70세 이상
            continue
        v = num(r["DT"])
        if v is not None:
            out.setdefault(r["PRD_DE"], {}).setdefault(sex, {}).setdefault(str(a), {})[
                {"평균소득": "mean", "중위소득": "median"}[r["ITM_NM"].strip()]] = v
    return out


def district_rate_series(name: str, item: str) -> dict:
    """{district: {year: rate}} for a multi-year district table."""
    rows = [r for r in raw(name) if r.get("ITM_ID", "") == item or r.get("ITM_NM") == item]
    index = name_index([r for r in rows if r["PRD_DE"] == max(x["PRD_DE"] for x in rows)])
    out: dict = {}
    for district in districts():
        code, _ = resolve(index, district)
        for r in rows:
            v = num(r["DT"])
            if code and r["C1"] == code and v is not None:
                out.setdefault(district, {})[r["PRD_DE"]] = round(v / 100, 4)
    return out


FULL_TO_KEY = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
               "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원도": "강원",
               "강원특별자치도": "강원", "충청북도": "충청북", "충청남도": "충청남", "전라북도": "전북", "전북특별자치도": "전북",
               "전라남도": "전라남", "경상북도": "경상북", "경상남도": "경상남", "제주특별자치도": "제주"}


def _band(label: str) -> str | None:
    """'25 - 29세' / 'ㆍ65 - 69세' / '75세 이상' / '80세이상' -> lower bound as a string."""
    m = re.match(r"^[ㆍ\s]*(\d+)\s*-\s*(\d+)\s*세$", label or "")
    if m and int(m.group(2)) - int(m.group(1)) == 4:
        return m.group(1)
    m = re.match(r"^[ㆍ\s]*(\d+)\s*세\s*이상$", label or "")
    return m.group(1) + "+" if m else None


def employment_series() -> dict:
    """{year: {sex: {band: employment rate}}}, bands 15/20/.../60/65/70/75+ (경제활동인구조사)."""
    out: dict = {}
    for r in raw("employment_series"):
        b, v = _band(r["C2_NM"]), num(r["DT"])
        if r["ITM_NM"] == "고용률" and b and v is not None and r["C1_NM"] in ("남자", "여자"):
            if b.endswith("+") and b not in ("75+",):
                continue
            out.setdefault(r["PRD_DE"], {}).setdefault(r["C1_NM"], {})[b] = round(v / 100, 4)
    return out


def migration_series(pop: dict) -> dict:
    """{year: {"od": {dest: {origin: movers}}, "inflow": {dest: in-movers / residents}, "age": {sex: {band: rate}}}}:
    interprovincial moves (인구이동통계). Rates use the December 2025 resident population."""
    residents: dict = defaultdict(float)
    by_age = {"남자": defaultdict(float), "여자": defaultdict(float)}
    for district, by_sex in pop["by_district"].items():
        for sex, ages in by_sex.items():
            for a, v in ages.items():
                residents[district.split("-")[0]] += v
                by_age[sex][a] += v
    out: dict = {}
    for r in raw("migration_od"):
        o, d, v = FULL_TO_KEY.get(r["C1_NM"].strip()), FULL_TO_KEY.get(r["C2_NM"].strip()), num(r["DT"])
        if r["ITM_NM"] == "이동자수" and o and d and o != d and v:
            out.setdefault(r["PRD_DE"], {"od": {}, "inflow": {}, "age": {}})["od"].setdefault(d, {})[o] = v
    for year, y in out.items():
        y["inflow"] = {d: round(sum(src.values()) / residents[d], 5) for d, src in y["od"].items() if residents.get(d)}
    for r in raw("migration_age"):
        b, v = _band(r["C3_NM"]), num(r["DT"])
        if r["ITM_NM"] == "시도간전입" and r["C2_NM"] in ("남자", "여자") and b and v is not None and r["PRD_DE"] in out:
            key = b.rstrip("+")
            n = sum(x for a, x in by_age[r["C2_NM"]].items() if (int(a) >= int(key) if b.endswith("+") else a == key))
            if n:
                out[r["PRD_DE"]]["age"].setdefault(r["C2_NM"], {})[b] = round(v / n, 5)
    return out


def repeat_movers() -> dict:
    """{sex: {band: {"five_year": share living in another 시도 five years earlier (2005 census), "annual": the five
    yearly interprovincial in-mover rates 2001-2005 for that band (over the 2005 census count)}}}."""
    census: dict = {}
    for r in raw("census2005_residence"):
        b = _band(r["C3_NM"].replace("~", " - "))
        if r["C2_NM"] in ("남자", "여자") and b and num(r["DT"]) is not None:
            census.setdefault(r["C2_NM"], {}).setdefault(b, {})[r["ITM_NM"]] = num(r["DT"])
    annual: dict = {}
    for r in raw("migration_age_2001"):
        b, v = _band(r["C3_NM"]), num(r["DT"])
        if r["ITM_NM"] == "시도간전입" and r["C2_NM"] in ("남자", "여자") and b and v is not None:
            annual.setdefault(r["C2_NM"], {}).setdefault(b, {})[r["PRD_DE"]] = v
    out: dict = {}
    for sex, bands in census.items():
        for b, c in bands.items():
            if not c.get("합계") or b not in annual.get(sex, {}):
                continue
            out.setdefault(sex, {})[b] = {"five_year": round(c["다른 시도"] / c["합계"], 5) if "다른 시도" in c else None,
                                          "annual": [round(annual[sex][b][y] / c["합계"], 5)
                                                     for y in sorted(annual[sex][b])]}
    return out


def vital_rates(name: str) -> dict:
    """{year: {sex: {band: events per person}}} nationwide from a 시도/성/연령별 rate table (per 1,000)."""
    out: dict = {}
    for r in raw(name):
        b, v = _band(r["C2_NM"]), num(r["DT"])
        if r["C1_NM"].strip() != "계" or not b or v is None or (b == "55+"):
            continue
        sex = "남자" if r["ITM_NM"].startswith("남편") else "여자"
        out.setdefault(r["PRD_DE"], {}).setdefault(sex, {})[b] = round(v / 1000, 6)
    return out


def life_table() -> dict:
    """{sex: {age lower bound: one-year death probability}} from the 2024 abridged life table (5-year q)."""
    out: dict = {"남자": {}, "여자": {}}
    for r in raw("life_table"):
        for sex in out:
            if r["ITM_NM"] == f"사망확률({sex})" and num(r["DT"]) is not None:
                a = r["C1_NM"].strip().rstrip("+")
                width = 1 if a == "0" else 4 if a == "1" else 5
                q = num(r["DT"])
                out[sex][a] = round(1 - (1 - min(q, 0.999999)) ** (1 / width), 6) if not r["C1_NM"].endswith("+") else round(min(q, 1.0) / 5 if q > 0.9 else q, 6)
    return out


def social_insurance() -> dict:
    """Employment insurance coverage of wage workers, regular vs non-regular."""
    rows = {(r["C1_NM"], r["ITM_NM"]): num(r["DT"]) for r in raw("social_insurance")}
    return {k: {"employment": round(rows[(k, "고용보험")] / 100, 4),
                "pension": round(rows[(k, "국민연금(직장가입자)")] / 100, 4),
                "health": round(rows[(k, "건강보험(직장가입자)")] / 100, 4)} for k in ("정규직", "비정규직")}


def main() -> None:
    pop = population()
    out = {
        "note": "공공통계로 만든 배정 확률표. 개인에 대한 사실이 아니라 통계적 가정. 출처·기준 시점은 sources.",
        "sources": {
            "population": "행정안전부 주민등록인구 2025-12, KOSIS 101 DT_1B04005N(시군구×5세×성)",
            "disability": "보건복지부 등록장애인 2025, KOSIS 101 DT_1DP2040(연령 및 성별 장애인 인구 - 시군구)",
            "livelihood": "보건복지부 국민기초생활보장 일반수급자 2025, KOSIS 117 DT_11714_N002(시도×성×연령)",
            "religion": "통계청 2015 인구주택총조사(표본), KOSIS 101 DT_1PM1502(성·연령·종교, 시도) — 종교 문항은 2015가 마지막",
            "commute": "통계청 2020 인구주택총조사(표본), KOSIS 101 DT_1PA2003(성·연령·교통수단별 통근, 시군구)",
            "smoking": "질병관리청 지역사회건강조사 2025, KOSIS 177 DT_H_SM·DT_H_SM_MALE(시군구 현재흡연율 조율)",
            "health_good": "질병관리청 지역사회건강조사 2025 주관적 건강수준 인지율, KOSIS 101 DT_1YL21011E(시군구)",
            "knhanes": "질병관리청 국민건강영양조사 2024, KOSIS 177 DT_11702_N001(현재흡연율)·DT_11702_N121(주관적 건강인지율) 성×연령",
            "chronic": "질병관리청 지역사회건강조사 2025 고혈압·당뇨병 진단 경험률(30세 이상), KOSIS 177 DT_HYPER_DOCTOR·"
                       "DT_DIA_DOCTOR(시군구) + 국민건강영양조사 2024 유병률 성×연령, DT_11702_N105·N102",
            "employment": "통계청 2020 인구주택총조사(표본), KOSIS 101 DT_1PC2006(성·연령·종사상지위별 취업인구, 시도)",
            "nps_oldage": "국민연금공단 2025 노령연금 연령별·성별·지역별 수급자, KOSIS 322 DT_32202_B049",
            "basic_pension": "통계청 연금통계 2024 연금종류별 수급률(기초·장애인연금, 65세 이상 연령대별), KOSIS 101 DT_1PEN_006",
            "networth": "가계금융복지조사 2025 순자산 5분위, KOSIS 101 DT_1HDAAA12 + DT_1HDAAB03(순자산 분위별 소득구간)",
            "dual_earner": "통계청 지역별고용조사 가구주 연령계층별 맞벌이 가구 비율, KOSIS 101 DT_1ES4F03S",
            "contract": "통계청 경제활동인구조사 근로형태별 부가조사, KOSIS 101 DT_1DE7006S(성·연령별 비정규직)",
            "digital": "과기정통부·NIA 스마트폰 과의존 실태조사 2025 디지털 사용 역량(DT_120019N_2021_027) + "
                       "디지털정보격차 실태조사 2025 고령층 역량 지수(DT_12017N0014), KOSIS 127",
            "elder": "보건복지부 노인실태조사 2023 기능상태 제한(DT_117071_C003)·돌봄 수급률(DT_117071_C004), KOSIS 117",
            "habits": "질병관리청 지역사회건강조사 2025 고위험음주율(DT_117075_H_DR_HIGH_WH)·자가보고 비만율(DT_H_OBE_OBE)·"
                      "걷기 실천율(DT_H_EX_WALK) 시군구 + 국민건강영양조사 2024 성×연령(DT_11702_N018·N101·N054), KOSIS 177",
            "mind": "질병관리청 지역사회건강조사 2025 스트레스 인지율(DT_H_MENTAL_STRESS)·우울감 경험률(DT_H_MENTAL_DEPRESS) 시군구 + "
                    "국민건강영양조사 2024 스트레스 인지율 성×연령(DT_11702_N061), KOSIS 177",
            "reading": "문화체육관광부 국민독서실태조사 2025 성인 종합 독서율, KOSIS 113 DT_113_STBL_1029672",
            "arts": "문화체육관광부 문화향수실태조사 2025 문화예술행사 관람률, KOSIS 113 DT_113_STBL_1026886",
            "pet": "농림축산식품부 2025 반려동물 양육 실태조사 현재 양육 여부, KOSIS 114 DT_114063_001",
            "social_insurance": "통계청 경제활동인구조사 근로형태별 부가조사 2026-08 사회보험 가입률, KOSIS 101 DT_1DE7081S",
            **{f"survey_{k}": v for k, v in SURVEY_SOURCES.items()},
            "finance": "통계청·금융감독원·한국은행 가계금융복지조사 2025, KOSIS 101 DT_1HDAAB03(가구특성별 소득구간)·"
                       "DT_1HDAAD01(가구특성별 부채 보유)·DT_1HDAAA06/03/04/09/01(연령·입주형태·가구원수·종사상지위·지역별)",
        },
        "population_name_matched": pop["name_matched"],
        "disability": disability(pop),
        "livelihood": livelihood(pop),
        "religion": religion(),
        "commute": commute(),
        "smoking": district_rate("smoking", "CR"),
        "smoking_male": district_rate("smoking_male", "CR"),
        "health_good": district_rate("health_good", "주관적 건강수준인지율"),
        "knhanes_smoking": knhanes("knhanes_smoking"),
        "knhanes_health": knhanes("knhanes_health"),
        "finance": finance(),
        "hypertension": district_rate("hypertension", "CR"),
        "diabetes": district_rate("diabetes", "CR"),
        "knhanes_hypertension": knhanes("knhanes_hypertension"),
        "knhanes_diabetes": knhanes("knhanes_diabetes"),
        "employment": employment(),
        "nps_oldage": nps_oldage(pop),
        "basic_pension": basic_pension(),
        "networth": networth(),
        "work_extra": work_extra(),
        "digital": digital(),
        "elder": elder(),
        "drinking": district_rate("drinking", "조율"),
        "obesity": district_rate("obesity", "조율"),
        "walking": district_rate("walking", "조율"),
        "stress": district_rate("stress", "조율"),
        "depression": district_rate("depression", "조율"),
        "knhanes_drinking": knhanes("knhanes_drinking"),
        "knhanes_obesity": knhanes("knhanes_obesity"),
        "knhanes_walking": knhanes("knhanes_walking"),
        "knhanes_stress": knhanes("knhanes_stress"),
        "reading": one_way("reading", "독서한 적 있음"),
        "arts": one_way("arts", "관람함"),
        "pet": one_way("pet", "현재 거주지에서 양육하고 있다"),
        "social_insurance": social_insurance(),
        **{f"survey_{k}": survey_share(t, parts, **opt) for k, (t, parts, opt) in SURVEY_SHARES.items()},
        "survey_driving_license": driving_license(pop),
        "history_income_mobility": income_mobility(),
        "history_income_change": income_change(),
        "history_wage_level": wage_level(),
        "history_smoking": district_rate_series("smoking_series", "조율"),
        "history_employment": employment_series(),
        "history_migration": migration_series(pop),
        "history_marriage": vital_rates("marriage_rate"),
        "history_divorce": vital_rates("divorce_rate"),
        "life_table": life_table(),
        "history_repeat_movers": repeat_movers(),
    }
    path = OFFICIAL / "persona_context.json"
    path.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB")
    print("population name-matched:", pop["name_matched"])
    print("disability levels:", out["disability"]["levels"], "not district:", out["disability"]["not_district"][:20])
    for k in ("smoking", "smoking_male", "health_good", "drinking", "obesity", "walking", "stress", "depression"):
        print(k, out[k]["levels"], "covered", len(out[k]["by_district"]))
    print("commute districts", len(out["commute"]), "religion provinces", len(out["religion"]),
          "livelihood provinces", len(out["livelihood"]))


if __name__ == "__main__":
    main()
