"""Life-context assignment: household income band, debt, car, basic livelihood receipt, registered disability,
religion, commute mode, smoking and self-rated health for panel members, drawn from public statistics.

The NVIDIA personas carry age, sex, district, occupation, education and household type but no economic, health or
belief attributes. Each attribute here is drawn from an official table conditioned on what the persona already says:

* household finances (income band, debt, car) — 2025 household finance survey shares by head age, head education,
  head employment, household size and tenure, plus mean income by tenure and by province. The survey publishes one-way tables only, so the panel is raked
  (iterative proportional fitting over people). This is a household-to-person approximation, not a person-weighted
  estimate: household IDs and exact household sizes are unavailable. Household shares cannot be recovered as
  population shares; incomplete published distributions are not used as raking targets;
* basic livelihood receipt — 2025 recipients / residents by province × sex × 5-year age, drawn only for people whose
  drawn household income is under 30 million won so the expected count is unchanged;
* registered disability — 2025 registered disabled / residents by district × sex × 5-year age;
* religion — 2015 census (the last census to ask) by province × sex × age ten years earlier (the same birth cohort);
* commute mode — 2020 census commuters by district × sex × 5-year age, for people with an occupation;
* smoking and self-rated health — the 2024 KNHANES sex × age shape raked to each district's 2025 community health
  survey rate (and the district's male rate for smoking).

Draws are seeded by the person's uuid, one stream per attribute, so a person keeps their attributes across runs.
When the persona's own text already talks about a subject (smoking, a disability, faith, money trouble, a car,
commuting, an illness) that attribute is left out instead of risking a contradiction. Everything is an assumption made
from statistics, not a fact about the person, and the profile block says so.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from functools import lru_cache
from pathlib import Path

from . import housing_context

OFFICIAL = Path(__file__).resolve().parents[1] / "series" / "official"
VERSION = "life-context-v2"
VALUE_SCHEMA = "life-context-values-v3"
FINANCE_LIMIT = "가구 기준 통계를 사람 패널에 맞춘 근사: 가구 연결키·정확한 가구원 수가 없어 개인 기준 비율로 해석할 수 없음"
INCOME_BANDS = ("lt10", "10_30", "30_50", "50_70", "70_100", "ge100")
INCOME_KO = {"lt10": "1천만 원 미만", "10_30": "1천만~3천만 원", "30_50": "3천만~5천만 원", "50_70": "5천만~7천만 원",
             "70_100": "7천만~1억 원", "ge100": "1억 원 이상"}
LOW_INCOME = ("lt10", "10_30")
# Band midpoints (만원) for matching published mean incomes; the open top band's 1.6억 makes the national band shares
# reproduce the survey's national mean (7,404 vs 7,427).
INCOME_MIDPOINT = {"lt10": 600, "10_30": 2000, "30_50": 4000, "50_70": 6000, "70_100": 8500, "ge100": 16000}
RELIGION_KO = {"none": "종교 없음", "buddhist": "불교", "protestant": "개신교", "catholic": "천주교", "other": "기타 종교"}
COMMUTE_KO = {"walk": "걸어서", "bike": "자전거", "car": "자가용(승용차·승합차·트럭)", "bus": "시내·마을버스",
              "shuttle": "통근버스", "intercity_bus": "고속·시외버스", "subway": "전철·지하철", "rail": "기차", "taxi": "택시",
              "other": "기타 수단", "multi": "두 가지 이상 갈아타기"}
EDU_HEAD = {"무학": "(가구주 교육수준) 초졸 이하", "초등학교": "(가구주 교육수준) 초졸 이하",
            "중학교": "(가구주 교육수준) 중졸", "고등학교": "(가구주 교육수준) 고졸"}
NO_JOB = {"무직"}
# Persona text that already speaks to an attribute; checked on the narrative only (the header lists the occupation).
PROFILE_MENTIONS = {
    "tenure": r"자가(?!용|진단|격리|발전)|전세|월세|사글세|무상 ?거주|내 ?집|자기 ?집|본인 ?소유|자기 ?소유|임대차|세입자|셋방|월셋",
    "finance": r"생활고|형편이 어려|형편이 넉넉|넉넉한 형편|부유|재력|자산가|건물주|빚을|빚이|부채|대출금|빠듯한 살림|가난",
    "car": r"운전대|자가용|승용차|드라이브|차를 몰|자동차를|내 차|자차|캠핑카|트럭을 몰",
    "commute": r"지하철|버스|출퇴근|자전거로|걸어서 출근|통근",
    "health": r"투병|지병|질환|당뇨|고혈압|관절염|만성|휠체어|투석",
    "religion": r"교회|목사|성당|천주교|신부님|수녀|사찰|불교|법회|스님|신앙|예배|미사|종교|찬양|성경|불경|절에 다",
    "smoking": r"흡연|담배|금연|애연",
    "disability": r"장애|휠체어|청각|시각을 잃|보청기",
    "livelihood": r"수급|기초생활|기초연금",
    "employment": r"사장님|사장으로|대표로|대표이사|운영하|가게를|자영업|농사를 짓|농장을|어선을|프리랜서|직원을 두",
    "pension": r"연금",
    "drinking": r"술을|술자리|음주|소주|맥주|막걸리|와인|양주|반주|금주",
    "obesity": r"비만|살이 쪄|살이 찐|체중|다이어트|뚱뚱|과체중",
    "walking": r"걷기|산책|등산|조깅|달리기|러닝|마라톤|만보",
    "mind": r"우울|스트레스|불면|공황|번아웃|불안장애|외로움",
    "reading": r"독서|책을|책 읽|책읽|소설|도서관|서점",
    "arts": r"공연|전시|미술관|연극|뮤지컬|콘서트|영화관|박물관|극장|영화를|영화 감상",
    "pet": r"반려|강아지|고양이|애견|애완|반려견|반려묘|댕댕",
    "civic": r"선거|투표|시민단체|서명운동|주민자치|청원|집회|시위|정치에 관심|정당",
    "volunteer": r"봉사",
    "travel": r"해외여행|해외 여행|배낭여행|여행을 (즐|다니|떠나)",
    "breakfast": r"아침(밥|식사)?을? ?(거르|굶|챙겨|꼭)",
    "shift": r"야간|밤샘|교대|밤 근무|새벽 근무",
    "insurance": r"보험",
}
PROVINCE_FULL = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
                 "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원특별자치도",
                 "충청북": "충청북도", "충청남": "충청남도", "전북": "전북특별자치도", "전라남": "전라남도", "경상북": "경상북도",
                 "경상남": "경상남도", "제주": "제주특별자치도"}
ONE_PERSON = {"혼자 거주", "혼자 거주 (배우자 별거)"}
TWO_PERSON = {"배우자와 거주", "어머니와 동거", "아버지와 동거"}
THREE_PLUS = {"배우자·자녀와 거주", "기타3세대", "배우자·자녀·어머니와 거주", "배우자·편부모와 거주", "배우자·자녀·부모와 거주",
              "부모·조모와 동거", "자녀·어머니와 거주", "배우자·자녀·아버지와 거주", "배우자·손자녀와 거주",
              "배우자·부모와 거주", "배우자·자녀·형제자매와 거주", "4세대이상", "부모·형제자매와 동거", "부모·조부모와 동거",
              "부모·친인척과 동거", "부모·조부와 동거", "배우자·미혼 형제자매와 거주", "자녀·아버지와 거주",
              "배우자·친인척과 거주", "배우자·형제자매와 거주", "형제 부부 가구에 동거"}
RAKE_ROUNDS = 60


@lru_cache(maxsize=1)
def tables() -> dict:
    return json.loads((OFFICIAL / "persona_context.json").read_text(encoding="utf-8"))


def _rng(seed: int, attr: str, uuid: str) -> random.Random:
    return random.Random(int(hashlib.sha256(f"{seed}:{attr}:{uuid}".encode()).hexdigest()[:16], 16))


def _draw(rng: random.Random, probs: dict):
    if not probs or any(v is None for v in probs.values()) or sum(probs.values()) <= 0:
        return None
    u, acc, last = rng.random(), 0.0, None
    for k, v in probs.items():
        acc += v
        last = k
        if u < acc:
            return k
    return last


def narrative(person: dict) -> str:
    text = person.get("profile") or ""
    return text.split("\n\n", 1)[1] if "\n\n" in text else text


def mentions(person: dict) -> set[str]:
    text = narrative(person)
    return {k for k, pat in PROFILE_MENTIONS.items() if re.search(pat, text)}


# ---- household traits used by the finance tables -------------------------------------------------------------

def is_head(person: dict) -> bool:
    return housing_context.head_age(person) == int(person["age"])


def head_age_key(person: dict) -> str:
    a = housing_context.head_age(person)
    if a < 30:
        return "29세 이하"
    if a >= 60:
        return "60세 이상"
    lo = a // 10 * 10
    return f"{lo}~{lo + 9}세"


def household_size(person: dict) -> str | None:
    ft = person.get("family_type") or ""
    if ft in ONE_PERSON:
        return "1"
    if ft in TWO_PERSON:
        return "2"
    if ft in THREE_PLUS:
        return "3+"
    return None  # 한부모·부모와 동거·기타 2세대 등은 2인인지 3인 이상인지 알 수 없음


def _mix(rows: dict, weights: dict) -> dict:
    if any(v is None for row in rows.values() for v in row.values()):
        return {b: None for b in next(iter(rows.values()))}
    total = sum(weights.values())
    return {b: sum(rows[k][b] * w for k, w in weights.items()) / total for b in next(iter(rows.values()))}


def employment_status(person: dict, seed: int) -> str | None:
    """Wage worker / self-employed (alone or with employees) / unpaid family worker for people with an occupation."""
    if (person.get("occupation") or "") in NO_JOB or "employment" in mentions(person):
        return None
    rows = tables()["employment"].get(person["province"], {}).get(person["sex"], {})
    shares = rows.get(_age5(int(person["age"]), 70))
    return _draw(_rng(seed, "employment", person["uuid"]), shares) if shares else None


def finance_constraints(people: list[dict], tenure: dict, status: dict | None = None) -> dict:
    """Household-to-person approximation, NOT population shares; see FINANCE_LIMIT.
    No household IDs or exact sizes exist to convert household weights to person weights.
    Incomplete targets are omitted rather than forcing unpublished categories to zero.
    """
    f = tables()["finance"]
    inc, debt = f["income_band"], f["debt_holding"]
    status_w = {"상용근로자": f["share_by_status"]["상용근로자"], "임시일용근로자": f["share_by_status"]["임시일용근로자"],
                "자영업자": f["share_by_status"]["자영업자"]}
    size_w = {k: f["share_by_size"][k.replace(" ", "")] for k in ("3인", "4인", "5인 이상")}

    def binary(rate: float) -> dict:
        return {"yes": rate, "no": 1 - rate} if rate is not None else {"yes": None, "no": None}

    groups: dict = {"income": {}, "debt": {}, "car": {}}

    def add(attr: str, key: str, i: int, target: dict) -> None:
        if any(v is None for v in target.values()):
            return
        groups[attr].setdefault(key, ([], target))[0].append(i)

    employed_inc = _mix({k: inc[f"(가구주 종사상지위) {n}"] for k, n in
                         (("상용근로자", "상용근로자"), ("임시일용근로자", "임시·일용근로자"), ("자영업자", "자영업자"))},
                        status_w)
    employed_debt = sum(debt[f"(가구주 종사상지위) {n}"] * status_w[k] for k, n in
                        (("상용근로자", "상용근로자"), ("임시일용근로자", "임시·일용근로자"), ("자영업자", "자영업자"))) / sum(
        status_w.values())
    wage_w = {k: status_w[k] for k in ("상용근로자", "임시일용근로자")}
    wage_inc = _mix({"상용근로자": inc["(가구주 종사상지위) 상용근로자"],
                     "임시일용근로자": inc["(가구주 종사상지위) 임시·일용근로자"]}, wage_w)
    wage_debt = (debt["(가구주 종사상지위) 상용근로자"] * wage_w["상용근로자"] +
                 debt["(가구주 종사상지위) 임시·일용근로자"] * wage_w["임시일용근로자"]) / sum(wage_w.values())
    big_inc = _mix({k: inc[f"(가구원수) {k}"] for k in size_w}, size_w)
    big_debt = sum(debt[f"(가구원수) {k}"] * w for k, w in size_w.items()) / sum(size_w.values())
    big_car = sum(f["car_by_size"][k.replace(" ", "")] * w for k, w in size_w.items()) / sum(size_w.values())
    car_age = {"29세 이하": "29세 이하", "30~39세": "30~39세", "40~49세": "40~49세", "50~59세": "50~59세",
               "60세 이상": "60세 이상"}
    tenure_key = {"own": "자기집", "jeonse": "전세", "monthly": "월세", "free": "기타"}
    for i, p in enumerate(people):
        age = head_age_key(p)
        inc_age = "(가구주 연령) " + age.replace("~", "-")
        add("income", inc_age, i, inc[inc_age])
        add("debt", inc_age, i, binary(debt[inc_age]))
        add("car", "age " + age, i, binary(f["car_by_age"][car_age[age]]))
        t = tenure_key[tenure[p["uuid"]]]
        add("income", "tenure " + t, i, {"mean": f["mean_income_by_tenure"][t]})
        add("income", "region " + p["province"], i, {"mean": f["mean_income_by_region"][PROVINCE_FULL[p["province"]]]})
        add("debt", "tenure " + t, i, binary(f["debt_by_tenure"][t]))
        add("car", "tenure " + t, i, binary(f["car_by_tenure"][t]))
        if is_head(p):
            edu = EDU_HEAD.get(p.get("education_level") or "", "(가구주 교육수준) 대졸 이상")
            add("income", edu, i, inc[edu])
            add("debt", edu, i, binary(debt[edu]))
            if (p.get("occupation") or "") in NO_JOB:
                add("income", "status none", i, inc["(가구주 종사상지위) 기타(무직·학생 등)"])
                add("debt", "status none", i, binary(debt["(가구주 종사상지위) 기타(무직학생 등)"]))
            elif (status or {}).get(p["uuid"]) == "wage":
                add("income", "status wage", i, wage_inc)
                add("debt", "status wage", i, binary(wage_debt))
            elif (status or {}).get(p["uuid"]) in ("self_alone", "employer"):
                add("income", "status self", i, inc["(가구주 종사상지위) 자영업자"])
                add("debt", "status self", i, binary(debt["(가구주 종사상지위) 자영업자"]))
            else:
                add("income", "status employed", i, employed_inc)
                add("debt", "status employed", i, binary(employed_debt))
        size = household_size(p)
        if size == "3+":
            add("income", "size 3+", i, big_inc)
            add("debt", "size 3+", i, binary(big_debt))
            add("car", "size 3+", i, binary(big_car))
        elif size:
            key = f"{size}인"
            add("income", "size " + size, i, inc[f"(가구원수) {key}"])
            add("debt", "size " + size, i, binary(debt[f"(가구원수) {key}"]))
            add("car", "size " + size, i, binary(f["car_by_size"][key]))
    return {attr: list(g.values()) for attr, g in groups.items()}


def _tilt(rows: list[dict], values: dict, target: float) -> float:
    """lambda such that the mean of sum_c p_c x_c e^(lambda x_c) / Z over rows equals target (x in 억 원)."""
    xs = {c: v / 10000 for c, v in values.items()}

    def mean(lam: float) -> float:
        acc = 0.0
        for row in rows:
            w = {c: row[c] * math.exp(lam * xs[c]) for c in xs}
            z = sum(w.values())
            acc += sum(w[c] * xs[c] for c in xs) / z if z else 0.0
        return acc / len(rows)

    lo, hi, goal = -8.0, 8.0, target / 10000
    for _ in range(40):
        mid = (lo + hi) / 2
        if mean(mid) < goal:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def rake(n: int, start: dict | list, constraints: list[tuple[list[int], dict]], rounds: int = RAKE_ROUNDS,
         values: dict | None = None) -> tuple:
    """Person-level IPF. start: one distribution for everyone, or a list of per-person distributions. A constraint
    target is a distribution over the categories, or {"mean": m} matched by exponential tilting over `values`.
    Returns (per-person distributions, worst gap: share points for distributions, relative error for means)."""
    cats = list((start if isinstance(start, dict) else start[0]).keys())
    probs = [dict(start) for _ in range(n)] if isinstance(start, dict) else [dict(x) for x in start]
    worst = 1.0
    for _ in range(rounds):
        worst = 0.0
        for members, target in constraints:
            if not members or any(v is None for v in target.values()):
                continue
            if "mean" in target:
                rows = [probs[i] for i in members]
                current = sum(sum(r[c] * values[c] for c in cats) for r in rows) / len(rows)
                worst = max(worst, abs(current - target["mean"]) / target["mean"])
                lam = _tilt(rows, values, target["mean"])
                factor = {c: math.exp(lam * values[c] / 10000) for c in cats}
            else:
                mean = {c: sum(probs[i][c] for i in members) / len(members) for c in cats}
                worst = max(worst, max(abs(mean[c] - target[c]) for c in cats))
                factor = {c: (target[c] / mean[c]) if mean[c] > 0 else 0.0 for c in cats}
            for i in members:
                row = probs[i]
                for c in cats:
                    row[c] *= factor[c]
                total = sum(row.values())
                for c in cats:
                    row[c] = row[c] / total if total else 1 / len(cats)
        if worst < 1e-4:
            break
    return probs, worst


def _age10(age: int) -> str:
    return "19" if age < 30 else ("70" if age >= 70 else str(age // 10 * 10))


def _age5(age: int, top: int = 85) -> str:
    return str(min(age // 5 * 5, top))


def health_probs(people: list[dict], kind: str) -> tuple[list[dict], float]:
    """Smoking, good self-rated health, or a hypertension/diabetes diagnosis: KNHANES sex × age shape raked to the
    district's KCHS rate (diagnoses: adults 30+ only)."""
    t = tables()
    shape = t[f"knhanes_{kind}"]
    start = [{"yes": shape[p["sex"]][_age10(int(p["age"]))], "no": 1 - shape[p["sex"]][_age10(int(p["age"]))]}
             for p in people]
    by_district: dict = {}
    by_district_male: dict = {}
    for i, p in enumerate(people):
        by_district.setdefault(p["district"], []).append(i)
        if p["sex"] == "남자":
            by_district_male.setdefault(p["district"], []).append(i)
    constraints = []
    if kind in ("hypertension", "diabetes"):
        # Internal placeholder only; build emits null + not_applicable for under-30s, including probabilities.
        for i, p in enumerate(people):
            if int(p["age"]) < 30:
                start[i] = {"yes": 0.0, "no": 1.0}
        source = t[kind]["by_district"]
        for d, members in by_district.items():
            adults = [i for i in members if int(people[i]["age"]) >= 30]
            if d in source and adults:
                r = source[d]["rate"]
                constraints.append((adults, {"yes": r, "no": 1 - r}))
    elif kind == "health":
        source = t["health_good"]["by_district"]
        for d, members in by_district.items():
            if d in source:
                r = source[d]["rate"]
                constraints.append((members, {"yes": r, "no": 1 - r}))
    else:
        # The district's all-adult and male rates come from respondents whose sex mix differs from the panel's, so
        # raking to both can be infeasible. Men get the male rate; women get the rate the two imply for the
        # district's panel sex mix, kept within 0.5–30%.
        total, male = t["smoking"]["by_district"], t["smoking_male"]["by_district"]
        for d, members in by_district.items():
            men = by_district_male.get(d, [])
            women = [i for i in members if people[i]["sex"] == "여자"]
            if d in male and men:
                r = male[d]["rate"]
                constraints.append((men, {"yes": r, "no": 1 - r}))
            if d in total and d in male and women:
                share_m = len(men) / len(members)
                r = min(0.30, max(0.005, (total[d]["rate"] - male[d]["rate"] * share_m) / (1 - share_m)))
                constraints.append((women, {"yes": r, "no": 1 - r}))
    return rake(len(people), start, constraints)


def commute_probs(person: dict) -> dict | None:
    c = tables()["commute"]
    district = person["district"]
    if district not in c:
        city = district.split(" ")[0]
        district = next((d for d in c if d.startswith(city + " ")), None)
        if district is None:
            return None
    rows = c[district][person["sex"]]
    return rows.get(_age5(int(person["age"]), 75)) or rows.get("all")


def build(people: list[dict], seed: int = 2026) -> tuple[dict, dict]:
    """({uuid: assignment}, diagnostics). people need uuid, age, sex, province, district, family_type, occupation,
    education_level, housing_type and profile."""
    t = tables()
    if any(t["finance"]["income_band"]["전체"].get(b) is None for b in INCOME_BANDS):
        raise ValueError("national household income distribution is incomplete; cannot assign income")
    tenure = {p["uuid"]: housing_context.assign(p, seed)["tenure"] for p in people}
    status = {p["uuid"]: employment_status(p, seed) for p in people}
    cons = finance_constraints(people, tenure, status)
    inc_probs, inc_gap = rake(len(people), t["finance"]["income_band"]["전체"], cons["income"],
                              values=INCOME_MIDPOINT)
    debt_probs, debt_gap = rake(len(people), {"yes": 0.59, "no": 0.41}, cons["debt"])
    car_probs, car_gap = rake(len(people), {"yes": 0.66, "no": 0.34}, cons["car"])
    smoke_probs, smoke_gap = health_probs(people, "smoking")
    good_probs, good_gap = health_probs(people, "health")
    hyper_probs, hyper_gap = health_probs(people, "hypertension")
    diab_probs, diab_gap = health_probs(people, "diabetes")

    # livelihood: P(recipient | low income) chosen so the expected recipients per cell equal the official rate
    cells: dict = {}
    for i, p in enumerate(people):
        cells.setdefault((p["province"], p["sex"], _age5(int(p["age"]))), []).append(i)
    low_mass = {k: sum(inc_probs[i][b] for i in v for b in LOW_INCOME) / len(v) for k, v in cells.items()}

    # basic pension (income-tested): within each 65+ age group the official receipt rate is filled from the lowest
    # drawn income bands up, the boundary band by chance
    out = {}
    for i, p in enumerate(people):
        uid, age = p["uuid"], int(p["age"])
        skip = mentions(p)
        a: dict = {"tenure": tenure[uid], "skipped": sorted(skip), "value_status": {}}
        if "finance" not in skip:
            a["income"] = _draw(_rng(seed, "income", uid), inc_probs[i])
            a["debt"] = _draw(_rng(seed, "debt", uid), debt_probs[i]) == "yes"
        if "car" not in skip:
            a["car"] = _draw(_rng(seed, "car", uid), car_probs[i]) == "yes"
        if "livelihood" not in skip and "finance" not in skip:
            key = (p["province"], p["sex"], _age5(age))
            rate = t["livelihood"].get(p["province"], {}).get(p["sex"], {}).get(_age5(age))
            cond = (0.0 if rate == 0 else min(1.0, rate / low_mass[key])) if rate is not None and (rate == 0 or low_mass[key] > 0) else None
            a["livelihood"] = (a["income"] in LOW_INCOME and _rng(seed, "livelihood", uid).random() < cond) if cond is not None else None
        if "disability" not in skip:
            rate = t["disability"]["rate"].get(p["district"], {}).get(p["sex"], {}).get(_age5(age, 95))
            a["disability"] = _rng(seed, "disability", uid).random() < rate if rate is not None else None
        if "religion" not in skip:
            shares = t["religion"].get(p["province"], {}).get(p["sex"], {}).get(_age5(max(age - 10, 0)))
            a["religion"] = _draw(_rng(seed, "religion", uid), shares or {})
        if "commute" not in skip:
            works = (p.get("occupation") or "") not in NO_JOB
            a["commute"] = _draw(_rng(seed, "commute", uid), commute_probs(p) or {}) if works else None
            if not works:
                a["value_status"]["commute"] = "not_applicable"
        if "smoking" not in skip:
            a["smoking"] = _draw(_rng(seed, "smoking", uid), smoke_probs[i]) == "yes"
        if "health" not in skip:
            a["health_good"] = _draw(_rng(seed, "health", uid), good_probs[i]) == "yes"
            for kind, probs in (("hypertension", hyper_probs), ("diabetes", diab_probs)):
                a[kind] = (_draw(_rng(seed, kind, uid), probs[i]) == "yes") if age >= 30 else None
                if age < 30:
                    a["value_status"][kind] = "not_applicable"
        if status[uid]:
            a["employment"] = status[uid]
        if "pension" not in skip and age >= 60:
            rate = t["nps_oldage"].get(p["province"], {}).get(p["sex"], {}).get(_age5(age, 80))
            a["nps"] = _rng(seed, "nps", uid).random() < rate if rate is not None else None
        a["probs"] = {"income": {k: round(v, 4) for k, v in inc_probs[i].items()},
                      "hypertension": round(hyper_probs[i]["yes"], 4) if age >= 30 else None,
                      "diabetes": round(diab_probs[i]["yes"], 4) if age >= 30 else None,
                      "debt": round(debt_probs[i]["yes"], 4), "car": round(car_probs[i]["yes"], 4),
                      "smoking": round(smoke_probs[i]["yes"], 4), "health_good": round(good_probs[i]["yes"], 4)}
        out[uid] = a
        for key, value in list(a.items()):
            if value is None:
                a["value_status"].setdefault(key, "unknown")
    basic_pension(people, out, seed)
    gaps = {"networth": assign_networth(people, out, tenure, seed), "elder": assign_elder(people, out, seed),
            "digital": assign_digital(people, out, seed)}
    assign_work_extra(people, out, seed)
    assign_insurance(people, out, seed)
    gaps.update(assign_habits(people, out, seed))
    gaps.update(assign_culture(people, out, seed))
    gaps.update(assign_surveys(people, out, seed))
    diag = {"value_schema": VALUE_SCHEMA, "finance_unit": "household_to_person_approximation", "limitations": [FINANCE_LIMIT],
            "addon_rake_gap": gaps, "rake_gap": {"income": inc_gap, "debt": debt_gap, "car": car_gap, "smoking": smoke_gap,
                         "health_good": good_gap, "hypertension": hyper_gap, "diabetes": diab_gap}}
    return out, diag


def basic_pension(people: list[dict], out: dict, seed: int) -> None:
    rates = tables()["basic_pension"]
    groups: dict = {}
    for p in people:
        age, a = int(p["age"]), out[p["uuid"]]
        if age >= 65 and "income" in a and "pension" not in a["skipped"]:
            groups.setdefault(str(min(age // 5 * 5, 80)), []).append(p["uuid"])
    for g, uuids in groups.items():
        counts = {b: sum(1 for u in uuids if out[u]["income"] == b) for b in INCOME_BANDS}
        need, take = rates[g] * len(uuids), {}
        for b in INCOME_BANDS:  # lowest band first
            take[b] = min(1.0, need / counts[b]) if counts[b] and need > 0 else 0.0
            need -= counts[b] * take[b]
        for u in uuids:
            out[u]["basic_pension"] = _rng(seed, "basic_pension", u).random() < take[out[u]["income"]]


QUINTILES = ("1", "2", "3", "4", "5")
FUNCTION_KO = {"iadl": "혼자 장보기·식사 준비·외출 같은 일상 관리에 도움이 필요함",
               "adl": "옷 입기·씻기·식사 같은 기본 일상생활에도 도움이 필요함"}
DIGITAL_KO = {"good": "인터넷·스마트폰으로 필요한 정보를 잘 찾음", "fair": "인터넷·스마트폰은 기본만 씀",
              "poor": "인터넷·스마트폰으로 필요한 정보를 찾기 어려워함"}
NETWORTH_KO = {"1": "하위 20%", "2": "하위 20~40%", "3": "중간(40~60%)", "4": "상위 20~40%", "5": "상위 20%"}
CONTRACT_KO = {True: "비정규직", False: "정규직"}


def _head_age_label(person: dict) -> str:
    return head_age_key(person)


def assign_networth(people: list[dict], out: dict, tenure: dict, seed: int) -> float | None:
    """Net worth quintile: P(quintile | drawn income band) by Bayes, raked to the published mean net worth by head age,
    tenure and province (quintile means as values)."""
    n = tables()["networth"]
    idx = [i for i, p in enumerate(people) if "income" in out[p["uuid"]]]
    start = []
    for i in idx:
        band = out[people[i]["uuid"]]["income"]
        w = {q: n["income_given_quintile"][q].get(band) for q in QUINTILES}
        if any(v is None for v in w.values()):
            out[people[i]["uuid"]]["networth"] = None
            out[people[i]["uuid"]]["value_status"]["networth"] = "unknown"
            start.append(None)
            continue
        total = sum(w.values()) or 1.0
        start.append({q: w[q] / total for q in QUINTILES})
    idx, start = ([i for i, row in zip(idx, start) if row is not None], [row for row in start if row is not None])
    if not idx:
        return None
    tenure_key = {"own": "자기집", "jeonse": "전세", "monthly": "월세", "free": "기타"}
    groups: dict = {}
    for j, i in enumerate(idx):
        p = people[i]
        for key, target in (("age " + _head_age_label(p), n["mean_by_age"][_head_age_label(p)]),
                            ("tenure " + tenure[p["uuid"]], n["mean_by_tenure"][tenure_key[tenure[p["uuid"]]]]),
                            ("region " + p["province"], n["mean_by_region"][PROVINCE_FULL[p["province"]]])):
            groups.setdefault(key, ([], {"mean": target}))[0].append(j)
    probs, gap = rake(len(idx), start, list(groups.values()), values={q: n["quintile_mean"][q] for q in QUINTILES})
    for j, i in enumerate(idx):
        uid = people[i]["uuid"]
        out[uid]["networth"] = _draw(_rng(seed, "networth", uid), probs[j])
    return gap


def _married_with_spouse(p: dict) -> bool:
    return (p.get("marital_status") or "").replace(" ", "") == "배우자있음" and "배우자" in (p.get("family_type") or "") \
        and "별거" not in (p.get("family_type") or "")


def assign_work_extra(people: list[dict], out: dict, seed: int) -> None:
    """Non-regular contract for wage workers (sex × age); dual earners among married people living with a spouse,
    drawn only for workers so the share of dual-earner households by head age matches."""
    w = tables()["work_extra"]
    for p in people:
        uid, age, a = p["uuid"], int(p["age"]), out[p["uuid"]]
        if a.get("employment") == "wage":
            key = "20-29세" if age < 30 else ("70세이상" if age >= 70 else ("60~69세" if age >= 60 else f"{age // 10 * 10}-{age // 10 * 10 + 9}세"))
            rate = w["nonregular_by_sex_age"][p["sex"]].get(key, w["nonregular_by_sex_age"][p["sex"]]["계"])
            a["nonregular"] = _rng(seed, "nonregular", uid).random() < rate
    dual = w["dual_earner_by_head_age"]
    bands: dict = {}
    for p in people:
        if _married_with_spouse(p):
            a = int(p["age"])
            band = "15-29세" if a < 30 else ("60세이상" if a >= 60 else f"{a // 10 * 10}-{a // 10 * 10 + 9}세")
            bands.setdefault(band, []).append(p)
    for band, members in bands.items():
        workers = [p for p in members if (p.get("occupation") or "") not in NO_JOB]
        cond = min(1.0, dual[band] * len(members) / len(workers)) if workers else 0.0
        for p in members:
            works = (p.get("occupation") or "") not in NO_JOB
            out[p["uuid"]]["dual_earner"] = works and _rng(seed, "dual", p["uuid"]).random() < cond


def _elder_household(p: dict) -> str:
    ft = p.get("family_type") or ""
    if ft in ONE_PERSON:
        return "노인독거"
    if ft == "배우자와 거주":
        return "노인부부"
    if "자녀" in ft:
        return "자녀동거"
    return "기타"


def _elder_education(p: dict) -> str:
    return {"무학": "무학", "초등학교": "초등학교", "중학교": "중학교", "고등학교": "고등학교"}.get(
        p.get("education_level") or "", "전문대학 이상")


def assign_elder(people: list[dict], out: dict, seed: int) -> float:
    """65+: functional limitation (노인실태조사 2023) raked by sex, age, household type and education; care receipt
    among the limited raked by the same traits."""
    e = tables()["elder"]
    idx = [i for i, p in enumerate(people) if int(p["age"]) >= 65 and "health" not in out[p["uuid"]]["skipped"]]

    def age_key(age: int) -> str:
        return "90세 이상" if age >= 90 else f"{age // 5 * 5}~{age // 5 * 5 + 4}세"

    def traits(p: dict) -> list[str]:
        return [p["sex"], age_key(int(p["age"])), _elder_household(p), _elder_education(p)]

    def constraints(members: list[int], table: dict) -> list:
        groups: dict = {}
        for j in members:
            for t in traits(people[idx[j]]):
                if t in table:
                    groups.setdefault(t, ([], table[t]))[0].append(j)
        return list(groups.values())

    func_table = {k: v for k, v in e["function"].items() if len(v) == 3}
    probs, gap = rake(len(idx), func_table["전체"], constraints(list(range(len(idx))), func_table))
    limited = []
    for j, i in enumerate(idx):
        uid = people[i]["uuid"]
        out[uid]["function"] = _draw(_rng(seed, "function", uid), probs[j])
        if out[uid]["function"] != "none":
            limited.append(j)
    care_table = {k: {"yes": v["yes"], "no": 1 - v["yes"]} for k, v in e["care"].items() if "yes" in v}
    cprobs, _ = rake(len(idx), care_table["전체"], constraints(limited, care_table))
    for j in limited:
        uid = people[idx[j]]["uuid"]
        out[uid]["care"] = _draw(_rng(seed, "care", uid), cprobs[j]) == "yes"
    return gap


def assign_digital(people: list[dict], out: dict, seed: int) -> float:
    """'Can find what I need online': 20-59 and 60-69 from the smartphone overdependence survey; 70+ scaled down by the
    digital divide survey's competence index (70+ vs 60s); 60+ raked by sex and monthly household income using the
    same index's relative levels."""
    d = tables()["digital"]

    def three(dist: dict) -> dict:
        return {"good": dist["매우 그렇다"], "fair": dist["그렇다"],
                "poor": dist["그렇지 않다"] + dist["전혀 그렇지 않다"]}

    young, sixties = three(d["find_online"]["20-59"]), three(d["find_online"]["60-69"])
    comp = d["elderly_competence"]
    pos60 = sixties["good"] + sixties["fair"]
    pos70 = pos60 * comp["70대 이상"] / comp["60대"]
    seventies = {"good": sixties["good"] / pos60 * pos70, "fair": sixties["fair"] / pos60 * pos70, "poor": 1 - pos70}
    start = [young if int(p["age"]) < 60 else (sixties if int(p["age"]) < 70 else seventies) for p in people]
    older = [i for i, p in enumerate(people) if int(p["age"]) >= 60]
    pos_all = sum(start[i]["good"] + start[i]["fair"] for i in older) / len(older) if older else 0.0

    def target(ratio: float) -> dict:
        pos = min(0.97, pos_all * ratio)
        base_good = sum(start[i]["good"] for i in older) / len(older) / pos_all
        return {"good": pos * base_good, "fair": pos * (1 - base_good), "poor": 1 - pos}

    monthly = {"lt10": "100만원 미만", "10_30": "100~199만원", "30_50": "300~399만원", "50_70": "400만원 이상",
               "70_100": "400만원 이상", "ge100": "400만원 이상"}
    groups: dict = {}
    for i in older:
        p = people[i]
        sex = "남성" if p["sex"] == "남자" else "여성"
        groups.setdefault(sex, ([], target(comp[sex] / comp["고령층 전체"])))[0].append(i)
        band = out[p["uuid"]].get("income")
        if band:
            key = monthly[band]
            groups.setdefault(key, ([], target(comp[key] / comp["고령층 전체"])))[0].append(i)
    probs, gap = rake(len(people), start, list(groups.values()))
    for i, p in enumerate(people):
        out[p["uuid"]]["digital"] = _draw(_rng(seed, "digital", p["uuid"]), probs[i])
    return gap


HABIT_KINDS = ("drinking", "obesity", "walking", "stress", "depression")
HABIT_SKIP = {"drinking": "drinking", "obesity": "obesity", "walking": "walking", "stress": "mind", "depression": "mind"}


def habit_probs(people: list[dict], kind: str) -> tuple[list[dict], float]:
    """High-risk drinking, self-reported obesity, regular walking, high stress, or a depressive episode: KNHANES sex ×
    age shape (none published for depression, so it starts flat) raked to the district's KCHS rate."""
    t = tables()
    shape = t.get(f"knhanes_{kind}")
    source = t[kind]["by_district"]
    flat = sum(v["rate"] for v in source.values()) / len(source)
    start = []
    for p in people:
        r = shape[p["sex"]][_age10(int(p["age"]))] if shape else flat
        start.append({"yes": r, "no": 1 - r})
    by_district: dict = {}
    for i, p in enumerate(people):
        by_district.setdefault(p["district"], []).append(i)
    constraints = [(m, {"yes": source[d]["rate"], "no": 1 - source[d]["rate"]})
                   for d, m in by_district.items() if d in source]
    return rake(len(people), start, constraints)


def assign_habits(people: list[dict], out: dict, seed: int) -> dict:
    gaps = {}
    for kind in HABIT_KINDS:
        probs, gaps[kind] = habit_probs(people, kind)
        for i, p in enumerate(people):
            a = out[p["uuid"]]
            if HABIT_SKIP[kind] not in a["skipped"]:
                a[kind] = _draw(_rng(seed, kind, p["uuid"]), probs[i]) == "yes"
    return gaps


# Monthly household income labels of the culture and pet surveys, from the drawn annual band (만원/12).
READING_INCOME = {"lt10": "200만원 미만", "10_30": "200만원 미만", "30_50": "300~400만원 미만", "50_70": "400~500만원 미만",
                  "70_100": "500만원 이상", "ge100": "500만원 이상"}
ARTS_INCOME = {"lt10": "100만원 미만", "10_30": "100~200만원", "30_50": "300~400만원", "50_70": "400~500만원",
               "70_100": "600만원 이상", "ge100": "600만원 이상"}
PET_INCOME = {"lt10": "300만 원 이하", "10_30": "300만 원 이하", "30_50": "301~500만 원", "50_70": "501만 원 이상",
              "70_100": "501만 원 이상", "ge100": "501만 원 이상"}
ARTS_WORK = {"self_alone": "고용원이 없는 자영업자", "employer": "고용원이 있는 자영업자", "family": "무급가족종사자"}
ARTS_PROVINCE = {"충청북": "충북", "충청남": "충남", "전라남": "전남", "경상북": "경북", "경상남": "경남"}
PET_REGION = {"서울": "서울/강원권", "강원": "서울/강원권", "인천": "경인권", "경기": "경인권", "대전": "충청권", "세종": "충청권",
              "충청북": "충청권", "충청남": "충청권", "광주": "호남권", "전북": "호남권", "전라남": "호남권", "대구": "대경권",
              "경상북": "대경권", "부산": "동남권", "울산": "동남권", "경상남": "동남권"}


def _culture_traits(kind: str, p: dict, a: dict) -> list[str]:
    age, sex, edu = int(p["age"]), ("남성" if p["sex"] == "남자" else "여성"), p.get("education_level") or ""
    size = household_size(p)
    band = a.get("income")
    if kind == "reading":
        out = [sex, "20대 이하" if age < 30 else ("70대 이상" if age >= 70 else f"{age // 10 * 10}대"),
               "중졸 이하" if edu in ("무학", "초등학교", "중학교") else ("고졸 고퇴" if edu == "고등학교" else "대재 이상")]
        return out + ([READING_INCOME[band]] if band else [])
    if kind == "arts":
        marital = (p.get("marital_status") or "").replace(" ", "")
        out = [sex, "70세이상" if age >= 70 else f"{age // 10 * 10}대",
               {"무학": "초졸 이하", "초등학교": "초졸 이하", "중학교": "중졸", "고등학교": "고졸"}.get(edu, "대졸이상"),
               {"미혼": "미혼", "배우자있음": "기혼"}.get(marital, "사별/이혼/기타"),
               ARTS_PROVINCE.get(p["province"], p["province"])]
        out += [{"1": "1인", "2": "2인", "3+": "3인이상"}[size]] if size else []
        out += ["장애등록" if a.get("disability") else "해당사항없음"] if a.get("disability") is not None else []
        if (p.get("occupation") or "") in NO_JOB:
            out.append("해당없음(무직)")
        elif a.get("employment") == "wage" and "nonregular" in a:
            out.append("임시근로자" if a["nonregular"] else "상용근로자")
        elif a.get("employment") in ARTS_WORK:
            out.append(ARTS_WORK[a["employment"]])
        return out + ([ARTS_INCOME[band]] if band else [])
    # pet: a household trait, surveyed from adults 20+
    housing = p.get("housing_type") or ""
    out = [sex, "60대 이상" if age >= 60 else ("20대" if age < 30 else f"{age // 10 * 10}대"),
           "아파트" if housing == "아파트" else ("단독주택" if housing == "단독주택" else "다세대/빌라/기타")]
    out += [PET_REGION[p["province"]]] if p["province"] in PET_REGION else []
    out += [{"1": "1명", "2": "2명", "3+": "3명 이상"}[size]] if size else []
    return out + ([PET_INCOME[band]] if band else [])


def assign_culture(people: list[dict], out: dict, seed: int) -> dict:
    """Read a book in the past year (국민독서실태조사), attended an arts event (문화향수실태조사), household keeps a pet
    (반려동물 양육 실태조사): each survey's one-way shares by sex, age, education, household and income raked jointly."""
    gaps = {}
    for kind in ("reading", "arts", "pet"):
        table = tables()[kind]
        groups: dict = {}
        for i, p in enumerate(people):
            for key in _culture_traits(kind, p, out[p["uuid"]]):
                if key in table:
                    groups.setdefault(key, ([], {"yes": table[key], "no": 1 - table[key]}))[0].append(i)
        start = {"yes": table["전체"], "no": 1 - table["전체"]}
        probs, gaps[kind] = rake(len(people), start, list(groups.values()))
        for i, p in enumerate(people):
            a = out[p["uuid"]]
            if kind not in a["skipped"]:
                a[kind] = _draw(_rng(seed, kind, p["uuid"]), probs[i]) == "yes"
    return gaps


def assign_insurance(people: list[dict], out: dict, seed: int) -> None:
    """Employment insurance for wage workers by contract type (근로형태별 부가조사)."""
    rates = tables()["social_insurance"]
    for p in people:
        a = out[p["uuid"]]
        if a.get("employment") == "wage" and "nonregular" in a:
            rate = rates["비정규직" if a["nonregular"] else "정규직"]["employment"]
            a["employment_insurance"] = _rng(seed, "employment_insurance", p["uuid"]).random() < rate


# ---- generic survey add-ons ------------------------------------------------------------------------------------
# One yes/no attribute per published one-way table ({category label: share}, compiled by build_persona_context.
# one_way). pp.survey_match reads which category each person falls in from the label, so a table needs only this spec:
#   table: key in persona_context.json   addon: module it belongs to   yes/no: profile line when True/False (None = omit)
#   eligible(person, assigned) -> bool   skip: PROFILE_MENTIONS key whose mention suppresses it
def _adult(p: dict, a: dict) -> bool:
    return True


def _working(p: dict, a: dict) -> bool:
    return p.get("occupation") != "무직"


def _youth(p: dict, a: dict) -> bool:
    return 19 <= int(p["age"]) <= 34


# Binary traits drawn from one-way survey tables (persona_context.json "survey_<attr>", built by
# scripts/build_persona_context.py). `yes`/`no` are the rendered lines (None = say nothing), `skip` a PROFILE_MENTIONS
# key whose mention in the narrative leaves the trait unassigned.
SURVEY_ATTRS: dict[str, dict] = {
    "voted_general": {"table": "survey_voted_general", "addon": "civic", "skip": "civic", "yes": None,
                      "no": "2024년 국회의원 선거에 투표하지 않음", "eligible": lambda p, a: int(p["age"]) >= 20},
    "petition": {"table": "survey_petition", "addon": "civic", "skip": "civic",
                 "yes": "지난 1년 서명운동에 참여한 적 있음"},
    "online_voice": {"table": "survey_online_voice", "addon": "civic", "skip": "civic",
                     "yes": "지난 1년 온라인에 정치·사회 의견을 올린 적 있음"},
    "contacted_official": {"table": "survey_contacted_official", "addon": "civic", "skip": "civic",
                           "yes": "지난 1년 공무원·정치인에게 민원을 전달한 적 있음"},
    "community_group": {"table": "survey_community_group", "addon": "civic", "skip": "civic",
                        "yes": "지역사회 공공모임(주민자치회 등)에 소속됨"},
    "volunteer": {"table": "survey_volunteer", "addon": "civic", "skip": "volunteer",
                  "yes": "지난 1년 자원봉사 활동을 함"},
    "lonely": {"table": "survey_lonely", "addon": "mind", "skip": "mind", "yes": "외로움을 느끼는 편"},
    "sleep_trouble": {"table": "survey_sleep_trouble", "addon": "mind", "skip": "mind", "eligible": _working,
                      "yes": "잠들기 어려운 날이 잦음(한 주에 여러 번 이상)"},
    "breakfast_skip": {"table": "survey_breakfast_skip", "addon": "habits", "skip": "breakfast",
                       "yes": "아침을 거르는 편"},
    "private_insurance": {"table": "survey_private_insurance", "addon": "medical", "skip": "insurance",
                          "yes": "민간의료보험(실손 등) 가입", "no": "민간의료보험 미가입"},
    "unmet_care": {"table": "survey_unmet_care", "addon": "medical",
                   "yes": "지난 1년 필요한 병의원 진료를 받지 못한 적 있음"},
    "night_work": {"table": "survey_night_work", "addon": "work", "skip": "shift", "eligible": _working,
                   "yes": "밤 근무를 함"},
    "shift_work": {"table": "survey_shift_work", "addon": "work", "skip": "shift", "eligible": _working,
                   "yes": "교대근무를 함"},
    "union": {"table": "survey_union", "addon": "work", "yes": "노동조합 가입",
              "eligible": lambda p, a: a.get("employment") == "wage" and "nonregular" in a},
    "retirement_pension": {"table": "survey_retirement_pension", "addon": "work", "yes": "퇴직연금 가입",
                           "eligible": lambda p, a: a.get("employment") == "wage" and "nonregular" in a},
    "long_hours": {"table": "survey_long_hours", "addon": "work", "eligible": _working, "yes": "주 50시간 이상 일함"},
    "worker_care": {"table": "survey_worker_care", "addon": "work", "eligible": _working,
                    "yes": "일하면서 노인·장애 가족을 돌봄(한 주에 여러 번 이상)"},
    "platform_self": {"table": "survey_platform_self", "addon": "work",
                      "eligible": lambda p, a: a.get("employment") in ("self_alone", "employer"),
                      "yes": "디지털 플랫폼(앱)을 통해 일감을 받음"},
    "protest": {"table": "survey_protest", "addon": "civic", "skip": "civic", "yes": "지난 1년 시위·집회에 참여한 적 있음"},
    "boycott": {"table": "survey_boycott", "addon": "civic", "skip": "civic", "yes": "지난 1년 불매운동에 참여한 적 있음"},
    "youth_no_help_sick": {"table": "survey_youth_no_help_sick", "addon": "youth", "eligible": _youth,
                           "yes": "본인이나 가족이 아플 때 도움받을 사람·기관이 없음"},
    "youth_mental_unmet": {"table": "survey_youth_mental_unmet", "addon": "youth", "eligible": _youth, "skip": "mind",
                           "yes": "정신건강 진료가 필요했지만 받지 못한 적 있음"},
    "youth_move": {"table": "survey_youth_move", "addon": "youth", "eligible": _youth,
                   "yes": "지금 사는 시도를 떠나 다른 지역으로 이사하고 싶음"},
    "driving_license": {"table": "survey_driving_license", "addon": "mobility", "skip": "car",
                        "eligible": lambda p, a: int(p["age"]) >= 20, "yes": None, "no": "운전면허 없음"},
    "kiosk_hard": {"table": "survey_kiosk_hard", "addon": "digital", "yes": "키오스크 주문·결제를 어려워함"},
    "senior_job": {"table": "survey_senior_job", "addon": "elder", "eligible": lambda p, a: int(p["age"]) >= 65,
                   "yes": "노인일자리사업에 참여 중"},
    "travel_abroad": {"table": "survey_travel_abroad", "addon": "culture", "skip": "travel",
                      "yes": "최근 1년 해외여행을 다녀옴"},
}


def assign_surveys(people: list[dict], out: dict, seed: int) -> dict:
    from pp import survey_match

    gaps = {}
    t = tables()
    for attr, spec in SURVEY_ATTRS.items():
        table = t.get(spec["table"])
        if not table or "전체" not in table:
            continue
        eligible = spec.get("eligible", _adult)
        idx = [i for i, p in enumerate(people) if eligible(p, out[p["uuid"]])]
        if table["전체"] is None:
            for i in idx:
                a = out[people[i]["uuid"]]
                if spec.get("skip") not in a["skipped"]:
                    a[attr] = None
                    a["value_status"][attr] = "unknown"
            continue
        groups: dict = {}
        for j, i in enumerate(idx):
            p = people[i]
            for label, share in table.items():
                if share is not None and survey_match.member(label, p, out[p["uuid"]]):
                    groups.setdefault(label, ([], {"yes": share, "no": 1 - share}))[0].append(j)
        start = {"yes": table["전체"], "no": 1 - table["전체"]}
        probs, gaps[attr] = rake(len(idx), start, list(groups.values()))
        for j, i in enumerate(idx):
            a = out[people[i]["uuid"]]
            if spec.get("skip") not in a["skipped"]:
                a[attr] = _draw(_rng(seed, attr, people[i]["uuid"]), probs[j]) == "yes"
    return gaps


def survey_lines(name: str, a: dict) -> list[str]:
    out = []
    for attr, spec in SURVEY_ATTRS.items():
        if spec["addon"] == name and attr in a:
            text = spec["yes"] if a[attr] else spec.get("no")
            if text:
                out.append(f"- {text}")
    return out


EMPLOYMENT_KO = {"wage": "임금근로자", "self_alone": "고용원 없는 자영업자", "employer": "고용원 있는 자영업자",
                 "family": "무급 가족 종사자"}

# Add-on modules sold on top of the base NVIDIA persona. Each renders its own lines; the service picks which to attach.
ADDONS = {
    "housing": {"title": "주거", "attributes": ["tenure"],
                "sources": ["2020 인구주택총조사(점유형태)", "2024 주거실태조사", "2024 주택소유통계"]},
    "finance": {"title": "가계 살림", "attributes": ["income", "debt", "car"],
                "sources": ["2025 가계금융복지조사"]},
    "assets": {"title": "자산", "attributes": ["networth"], "sources": ["2025 가계금융복지조사(순자산 5분위)"]},
    "welfare": {"title": "복지·연금", "attributes": ["livelihood", "disability", "nps", "basic_pension"],
                "sources": ["2025 기초생활보장 수급자", "2025 등록장애인", "2025 국민연금 노령연금 수급자", "2024 연금통계"]},
    "work": {"title": "일", "attributes": ["employment", "nonregular", "employment_insurance", "dual_earner", "commute"],
             "sources": ["2020 인구주택총조사(종사상지위·통근)", "경제활동인구조사 근로형태별 부가조사(비정규직·고용보험)",
                         "지역별고용조사(맞벌이)"]},
    "health": {"title": "건강", "attributes": ["smoking", "hypertension", "diabetes"],
               "sources": ["2025 지역사회건강조사", "2024 국민건강영양조사"]},
    "habits": {"title": "생활습관", "attributes": ["drinking", "obesity", "walking"],
               "sources": ["2025 지역사회건강조사", "2024 국민건강영양조사"]},
    "mind": {"title": "마음 건강", "attributes": ["stress", "depression"],
             "sources": ["2025 지역사회건강조사", "2024 국민건강영양조사"]},
    "elder": {"title": "고령 돌봄", "attributes": ["function", "care"], "sources": ["2023 노인실태조사"]},
    "digital": {"title": "디지털", "attributes": ["digital"],
                "sources": ["2025 스마트폰 과의존 실태조사", "2025 디지털정보격차 실태조사"]},
    "culture": {"title": "여가·문화", "attributes": ["reading", "arts"],
                "sources": ["2025 국민독서실태조사", "2025 문화향수실태조사"]},
    "pet": {"title": "반려동물", "attributes": ["pet"], "sources": ["2025 반려동물 양육 실태조사"]},
    "belief": {"title": "종교", "attributes": ["religion"], "sources": ["2015 인구주택총조사(종교)"]},
    "civic": {"title": "시민 참여", "attributes": [], "sources": ["2025 사회통합실태조사", "2025 국민여가활동조사(자원봉사)"]},
    "medical": {"title": "의료 이용", "attributes": [], "sources": ["2023 한국의료패널"]},
    "youth": {"title": "청년 생활", "attributes": [], "sources": ["2024 청년 삶 실태조사"]},
    "mobility": {"title": "이동", "attributes": [], "sources": ["2024 운전면허 소지자(경찰청)·주민등록인구"]},
}
# Survey-table traits join their add-on's attribute and source lists.
for _attr, _spec in SURVEY_ATTRS.items():
    ADDONS[_spec["addon"]]["attributes"].append(_attr)
for _name, _src in {"mind": "2025 사회통합실태조사(외로움)·2023 근로환경조사(수면)", "habits": "2024 국민건강영양조사(아침 결식)",
                    "work": "2023 근로환경조사(밤·교대 근무·근무시간·가족 돌봄·플랫폼)·2025 고용형태별 근로실태조사(노조·퇴직연금)", "digital": "2025 디지털 역량 조사(키오스크)",
                    "elder": "2023 노인실태조사(노인일자리)", "culture": "2025 해외여행 경험률"}.items():
    ADDONS[_name]["sources"].append(_src)
ALL_ADDONS = tuple(ADDONS)
BASE_ADDON_NAMES = {"housing", "finance", "assets", "welfare", "work", "health", "habits", "mind", "elder", "digital",
                    "culture", "pet", "belief"}
# Topical add-ons are attached only when the policy or question touches their topic: on unrelated questions their lines
# add noise (eval all13: health/mind lines pulled self-rated health toward "fair/poor"). The rest is the core bundle.
TOPICAL = {
    "habits": r"음주|술자리|술값|술집|주류|소주|맥주|주점|비만|체중|운동|걷기|체육|신체활동|흡연|담배|금연|건강증진|생활습관",
    "mind": r"정신건강|정신 건강|우울|스트레스|자살|마음 ?건강|심리|상담|고립|외로움|은둔|번아웃",
    "culture": r"문화|예술|공연|전시회|영화|독서|도서관|도서|책 ?읽|출판|서점|관광|여가|축제|박물관|미술관",
    "pet": r"반려|동물|강아지|고양이|애견|유기견|유기묘|펫",
    "civic": r"투표|선거|청원|서명운동|공청회|의견수렴|주민참여|참여예산|주민자치|시민단체|자원봉사|봉사활동|민원|정치|시민 ?참여",
    "youth": r"청년|대학생|사회초년생|취업 ?준비|취준|첫 ?직장|신혼|2030|MZ|지역 ?정착|정주|인구 ?유출|지방 ?소멸|귀향|이주",
    "mobility": r"교통|운전|면허|자동차|버스|지하철|철도|택시|도로|주차|통학|통근|고령 ?운전|이동권|자율주행|킥보드",
    "medical": r"의료|병원|의원|진료|건강보험|실손|보험료|응급|치과|약국|간병|수술|의사|의대|입원|외래|본인부담",
}
CORE_ADDONS = tuple(x for x in ALL_ADDONS if x not in TOPICAL)


def auto_addons(text: str) -> tuple[str, ...]:
    """Core add-ons plus the topical ones whose topic the text mentions."""
    topical = {name for name, pat in TOPICAL.items() if re.search(pat, text or "")}
    return tuple(x for x in ALL_ADDONS if x in CORE_ADDONS or x in topical)


def addons_from_version(version: str | None) -> tuple[str, ...]:
    """Add-on names recorded in a panel version ('<hash>+addons-<names>-<hash>'); () for the plain panel."""
    m = re.search(r"\+addons-(.+)-[0-9a-f]{8}$", version or "")
    if not m:
        return ()
    names = ALL_ADDONS if m.group(1) == "all" else tuple(m.group(1).split("."))
    return tuple(x for x in names if x in ADDONS)


def _lines(name: str, a: dict) -> list[str]:
    return (_base_lines(name, a) if name in BASE_ADDON_NAMES else []) + survey_lines(name, a)


def _base_lines(name: str, a: dict) -> list[str]:
    if name == "housing":
        return [f"- 주거 점유: {housing_context.TENURE_KO[a['tenure']]}"] if "tenure" not in a["skipped"] else []
    if name == "finance":
        out = []
        if "income" in a:
            out += [f"- 가구 연소득(전년): {INCOME_KO[a['income']]}", f"- 가구 부채: {'있음' if a['debt'] else '없음'}"]
        if "car" in a:
            out.append(f"- 자동차: {'가구가 보유' if a['car'] else '가구에 없음'}")
        return out
    if name == "assets":
        return [f"- 가구 순자산: 전체 가구 중 {NETWORTH_KO[a['networth']]}"] if "networth" in a else []
    if name == "welfare":
        flags = (("livelihood", "기초생활보장 수급 가구"), ("disability", "등록 장애인"),
                 ("nps", "국민연금(노령연금) 받음"), ("basic_pension", "기초연금 받음"))
        return [f"- {text}" for key, text in flags if a.get(key)]
    if name == "work":
        out = []
        if "employment" in a:
            kind = EMPLOYMENT_KO[a["employment"]]
            if "nonregular" in a:
                insured = a.get("employment_insurance")
                extra = "" if insured is None else (", 고용보험 가입" if insured else ", 고용보험 미가입")
                kind += f"({CONTRACT_KO[a['nonregular']]}{extra})"
            out.append(f"- 일하는 형태: {kind}")
        if a.get("dual_earner"):
            out.append("- 맞벌이 부부")
        if "commute" in a:
            out.append(f"- 출퇴근 수단: {COMMUTE_KO[a['commute']]}")
        return out
    if name == "health":
        out = [f"- 흡연: {'현재 흡연' if a['smoking'] else '비흡연'}"] if "smoking" in a else []
        out += [f"- {t}" for key, t in (("hypertension", "고혈압 진단 받음"), ("diabetes", "당뇨병 진단 받음")) if a.get(key)]
        return out
    if name == "elder":
        if a.get("function") in FUNCTION_KO:
            return [f"- {FUNCTION_KO[a['function']]}" + (" — 가족·돌봄 서비스의 도움을 받음" if a.get("care") else
                                                         " — 도와주는 사람 없음")]
        return []
    if name == "digital":
        return [f"- {DIGITAL_KO[a['digital']]}"] if "digital" in a else []
    if name == "belief":
        return [f"- 종교: {RELIGION_KO[a['religion']]}"] if "religion" in a else []
    if name == "habits":
        out = ["- 고위험 음주(한 번에 남자 7잔·여자 5잔 이상을 주 2회 이상)"] if a.get("drinking") else []
        out += ["- 비만(체질량지수 25 이상)"] if a.get("obesity") else []
        # only the positive case: "doesn't walk regularly" on half the panel read as poor health (eval all13)
        return out + (["- 걷기 운동을 꾸준히 함(주 5일 이상, 하루 30분 이상)"] if a.get("walking") else [])
    if name == "mind":
        out = ["- 평소 스트레스를 많이 느낌"] if a.get("stress") else []
        return out + (["- 지난 1년 사이 2주 넘게 우울감을 느낀 적 있음"] if a.get("depression") else [])
    if name == "culture":
        out = [f"- 지난 1년 책: {'1권 이상 읽음' if a['reading'] else '한 권도 읽지 않음'}"] if "reading" in a else []
        if "arts" in a:
            out.append(f"- 지난 1년 공연·전시·영화 관람: {'함' if a['arts'] else '안 함'}")
        return out
    if name == "pet":
        return ["- 집에서 반려동물을 키움"] if a.get("pet") else []
    raise KeyError(name)


def parse_addons(spec: str | list | tuple | None) -> tuple[str, ...]:
    """'all' / comma list / iterable -> ordered tuple of known add-on names."""
    if spec in (None, "", "all"):
        return ALL_ADDONS
    names = [x.strip() for x in spec.split(",")] if isinstance(spec, str) else list(spec)
    unknown = [x for x in names if x not in ADDONS]
    if unknown:
        raise ValueError(f"unknown add-ons: {unknown}; known: {list(ADDONS)}")
    return tuple(x for x in ALL_ADDONS if x in names)


def block(a: dict, addons: str | list | tuple | None = None) -> str:
    """The profile lines given to the model, for the chosen add-ons (default all). Rare attributes appear only when
    present."""
    a = {k: v for k, v in a.items() if v is not None}
    lines = []
    for name in parse_addons(addons):
        lines += _lines(name, a)
    if not lines:
        return ""
    head = "[공공통계로 배정한 생활 여건 — 이 사람에 대한 사실이 아니라, 같은 지역·나이·성별·가구 특성의 통계에서 뽑은 가정]"
    return "\n".join([head, *lines])
