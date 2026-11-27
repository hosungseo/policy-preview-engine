"""Which published-table category a panel member falls in, read from the category label itself.

Survey tables on KOSIS break a share down by one trait at a time ("남성", "30대", "대졸 이상", "월 300~400만원",
"1인 가구", "서울", "상용근로자" ...). `member(label, person, assigned)` answers True/False when the label names a trait
the panel knows (base persona fields or an already-assigned life-context attribute) and None when it does not, so a
table can be raked on every dimension it shares with the panel without hand-written mappings per table.
"""
from __future__ import annotations

import hashlib
import re

# Annual household income bands (만원). A survey's finer monthly bands are matched by a point inside the drawn band,
# placed by the person's uuid so members of one band spread across the finer categories.
INCOME_RANGE = {"lt10": (300, 1000), "10_30": (1000, 3000), "30_50": (3000, 5000), "50_70": (5000, 7000),
                "70_100": (7000, 10000), "ge100": (10000, 22000)}


def _income_point(band: str, uuid: str) -> float:
    lo, hi = INCOME_RANGE[band]
    u = int(hashlib.sha256(f"income-point|{uuid}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return lo + u * (hi - lo)
PROVINCES = {
    "서울": ("서울",), "부산": ("부산",), "대구": ("대구",), "인천": ("인천",), "광주": ("광주",), "대전": ("대전",),
    "울산": ("울산",), "세종": ("세종",), "경기": ("경기",), "강원": ("강원",), "충청북": ("충북", "충청북도"),
    "충청남": ("충남", "충청남도"), "전북": ("전북", "전라북도", "전북특별자치도"), "전라남": ("전남", "전라남도"),
    "경상북": ("경북", "경상북도"), "경상남": ("경남", "경상남도"), "제주": ("제주",),
}
CAPITAL = {"서울", "인천", "경기"}
REGION_GROUPS = {"서울/강원권": {"서울", "강원"}, "경인권": {"인천", "경기"}, "충청권": {"대전", "세종", "충청북", "충청남"},
                 "호남권": {"광주", "전북", "전라남"}, "대경권": {"대구", "경상북"}, "동남권": {"부산", "울산", "경상남"},
                 "강원권": {"강원"}, "제주권": {"제주"}, "대구경북권": {"대구", "경상북"}, "부산울산경남권": {"부산", "울산", "경상남"},
                 "인천·경기": {"인천", "경기"}, "대전·세종·충청·강원": {"대전", "세종", "충청북", "충청남", "강원"},
                 "광주·전라·제주": {"광주", "전북", "전라남", "제주"}, "부산·울산·경남": {"부산", "울산", "경상남"},
                 "대구·경북": {"대구", "경상북"}}
EDU_RANK = {"무학": 0, "초등학교": 1, "중학교": 2, "고등학교": 3, "2~3년제 전문대학": 4, "4년제 대학교": 5, "대학원": 6}
ONE = {"혼자 거주", "혼자 거주 (배우자 별거)"}
TWO = {"배우자와 거주", "어머니와 동거", "아버지와 동거"}
THREE_PLUS = {"배우자·자녀와 거주", "기타3세대", "배우자·자녀·어머니와 거주", "배우자·편부모와 거주", "배우자·자녀·부모와 거주",
              "배우자·자녀·아버지와 거주"}


def _norm(label: str) -> str:
    return re.sub(r"[\s ()]", "", label or "").replace("∼", "~").replace("－", "-").replace("–", "-")


def _age(label: str, age: int) -> bool | None:
    s = _norm(label)
    if "세" not in s and "대" not in s:
        return None
    if re.search(r"(학년|학생|중\d|고\d|대학|대재|대졸|대학원|대도시|대경|세대|가구)", s):
        return None
    m = re.fullmatch(r"(?:만)?(\d+)세?[~-](?:만)?(\d+)세", s)
    if m:
        return int(m.group(1)) <= age <= int(m.group(2))
    m = re.fullmatch(r"(\d+)세이상~(\d+)세미만", s)
    if m:
        return int(m.group(1)) <= age < int(m.group(2))
    m = re.fullmatch(r"(?:만)?(\d+)세(이상|이하|미만|초과)", s)
    if m:
        n, op = int(m.group(1)), m.group(2)
        return {"이상": age >= n, "이하": age <= n, "미만": age < n, "초과": age > n}[op]
    m = re.fullmatch(r"(\d+)대(이상|이하)?", s)
    if m:
        lo, op = int(m.group(1)), m.group(2)
        if op == "이상":
            return age >= lo
        if op == "이하":
            return age < lo + 10
        return lo <= age < lo + 10
    m = re.fullmatch(r"(\d+)세", s)
    if m:
        return age == int(m.group(1))
    return None


def _sex(s: str, sex: str) -> bool | None:
    if s in ("남", "남자", "남성"):
        return sex == "남자"
    if s in ("여", "여자", "여성"):
        return sex == "여자"
    return None


def _edu(s: str, edu: str | None) -> bool | None:
    if edu not in EDU_RANK:
        return None
    r = EDU_RANK[edu]
    table = {
        "무학": r == 0, "초졸이하": r <= 1, "초등학교졸업이하": r <= 1, "초졸": r == 1, "중졸이하": r <= 2, "중졸": r == 2,
        "중학교": r == 2, "고졸": r == 3, "고졸고퇴": r == 3, "고졸이하": r <= 3, "고등학교": r == 3,
        "전문대졸": r == 4, "대졸이상": r >= 4, "대재이상": r >= 4, "대학이상": r >= 4, "대학교이상": r >= 4,
        "4년제대학이상": r >= 5, "대졸": r in (4, 5), "대학원이상": r == 6, "대학원": r == 6,
        "초등학교": r == 1, "대학교4년제미만": r == 4, "대학교4년제이상": r == 5, "23년제전문대학": r == 4,
        "4년제이상대학": r == 5, "전문대학이상": r >= 4,
    }
    return table.get(s)


def _marital(s: str, marital: str | None) -> bool | None:
    m = (marital or "").replace(" ", "")
    if not m:
        return None
    table = {"미혼": m == "미혼", "기혼": m == "배우자있음", "유배우": m == "배우자있음", "배우자있음": m == "배우자있음",
             "배우자없음": m != "배우자있음", "유배우사실혼비혼동거포함": m == "배우자있음", "이혼또는별거": m == "이혼",
             "사별": m == "사별", "이혼": m == "이혼", "사별/이혼": m in ("사별", "이혼"), "이혼/사별": m in ("사별", "이혼"),
             "사별/이혼/기타": m in ("사별", "이혼"), "이혼·사별": m in ("사별", "이혼"), "사별·이혼": m in ("사별", "이혼")}
    return table.get(s)


def _household(s: str, family: str | None) -> bool | None:
    size = 1 if family in ONE else 2 if family in TWO else 3 if family in THREE_PLUS else None
    if size is None:
        return None
    m = re.fullmatch(r"(\d)(?:인|명|인가구)(이상)?(?:가구)?", s)
    if not m:
        return {"1인가구": size == 1, "다인가구": size >= 2}.get(s)
    n = int(m.group(1))
    if m.group(2):
        return size >= n if n <= 3 else None
    return size == n if n <= 2 else None  # 3-person vs 4+ unknown from family type


def _income(s: str, band: str | None, uuid: str = "") -> bool | None:
    """Monthly household income bands in 만원 (or 억/천만원 annual) against the drawn annual band's midpoint."""
    if not band or "만원" not in s and "만 원" not in s:
        return None
    t = re.sub(r"\s", "", s).replace("만원", "").replace(",", "").replace("∼", "~")
    t = re.sub(r"^(\d+)-(\d+)", r"\1~\2", t)
    # +0.5 keeps band midpoints (e.g. 500) off category boundaries
    annual = _income_point(band, uuid)
    monthly = annual if "월" not in s and "연" in s else annual / 12  # an annual band, else monthly
    t = t.replace("월", "").replace("연", "").replace("평균", "")
    t = re.sub(r"^(\d+)-(\d+)", r"\1~\2", t)
    m = re.fullmatch(r"(\d+)~(\d+)(미만)?", t)
    if m:
        hi = int(m.group(2))
        return int(m.group(1)) <= monthly < (hi + 1 if not m.group(3) and hi % 10 == 9 else hi)
    m = re.fullmatch(r"(\d+)(미만|이하)", t)
    if m:
        return monthly < int(m.group(1)) + (1 if m.group(2) == "이하" else 0)
    m = re.fullmatch(r"(\d+)(이상|초과)", t)
    if m:
        return monthly >= int(m.group(1))
    return None


def _region(s: str, province: str) -> bool | None:
    for key, names in PROVINCES.items():
        if s in names or s == PROVINCE_FULL.get(key):
            return province == key
    for group, members in REGION_GROUPS.items():
        if s == group:
            return province in members
    if s in ("수도권",):
        return province in CAPITAL
    if s in ("비수도권",):
        return province not in CAPITAL
    return None


PROVINCE_FULL = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
                 "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원특별자치도",
                 "충청북": "충청북도", "충청남": "충청남도", "전북": "전북특별자치도", "전라남": "전라남도", "경상북": "경상북도",
                 "경상남": "경상남도", "제주": "제주특별자치도"}


def _work(s: str, occupation: str | None, a: dict) -> bool | None:
    jobless = (occupation or "") == "무직"
    emp, nonreg = a.get("employment"), a.get("nonregular")
    s = {"임금봉급근로자": "임금근로자", "고용원있는사업주": "고용원이있는자영업자", "고용원없는자영자": "고용원이없는자영업자",
         "고용인이있는자영업자": "고용원이있는자영업자", "고용인이없는자영업자": "고용원이없는자영업자",
         "고용원있는자영업자": "고용원이있는자영업자", "고용원없는자영업자": "고용원이없는자영업자"}.get(s, s)
    if s in ("취업자", "취업", "일함", "경제활동"):
        return not jobless
    if s in ("미취업", "비취업", "무직", "비경제활동", "해당없음무직", "미취업자"):
        return jobless
    if jobless and s in ("임금근로자", "상용근로자", "상용", "임시근로자", "일용근로자", "임시·일용", "임시일용", "정규직",
                         "비정규직", "자영업자", "비임금근로자", "고용원이있는자영업자", "고용원이없는자영업자", "무급가족종사자"):
        return False
    if emp is None:
        return None
    table = {"임금근로자": emp == "wage", "비임금근로자": emp != "wage", "자영업자": emp in ("self_alone", "employer"),
             "고용원이있는자영업자": emp == "employer", "고용원이없는자영업자": emp == "self_alone",
             "무급가족종사자": emp == "family"}
    if s in table:
        return table[s]
    if nonreg is None or emp != "wage":
        return False if s in ("상용근로자", "상용", "정규직", "임시근로자", "일용근로자", "임시·일용", "임시일용", "비정규직", "정규근로자",
                                       "비정규근로자특수형태제외") and emp else None
    return {"상용근로자": not nonreg, "상용": not nonreg, "정규직": not nonreg, "비정규직": nonreg,
            "정규근로자": not nonreg, "비정규근로자특수형태제외": nonreg,
            "임시·일용": nonreg, "임시일용": nonreg, "임시근로자": nonreg}.get(s)


def _housing(s: str, housing: str | None, tenure: str | None) -> bool | None:
    if housing:
        h = {"아파트": housing == "아파트", "단독주택": housing == "단독주택",
             "연립/다세대": housing in ("연립주택", "다세대주택"), "연립·다세대": housing in ("연립주택", "다세대주택"),
             "다세대/빌라/기타": housing not in ("아파트", "단독주택")}.get(s)
        if h is not None:
            return h
    if tenure:
        return {"자가": tenure == "own", "자기집": tenure == "own", "전세": tenure == "jeonse", "월세": tenure == "monthly",
                "보증금있는월세": tenure == "monthly"}.get(s)
    return None


def member(label: str, person: dict, assigned: dict | None = None) -> bool | None:
    """True/False if the category label names a trait the panel member has (or lacks); None if it is not a trait the
    panel knows (the category is then left out of the raking)."""
    a = assigned or {}
    s = _norm(label)
    if not s or s in ("전체", "계", "소계", "전국"):
        return None
    for test in (lambda: _sex(s, person.get("sex")), lambda: _age(label, int(person["age"])),
                 lambda: _edu(s, person.get("education_level")), lambda: _marital(s, person.get("marital_status")),
                 lambda: _household(s, person.get("family_type")),
                 lambda: ((person.get("family_type") in ONE and int(person["age"]) >= 65) if s == "노인독거" else None),
                 lambda: _income(label.strip(), a.get("income"), person.get("uuid", "")),
                 lambda: _region(s, person.get("province", "")), lambda: _work(s, person.get("occupation"), a),
                 lambda: _housing(s, person.get("housing_type"), a.get("tenure")),
                 lambda: ({"장애인": a["disability"], "장애등록": a["disability"], "비장애인": not a["disability"],
                           "장애있음": a["disability"], "장애없음": not a["disability"]}.get(s)
                          if "disability" in a else None)):
        got = test()
        if got is not None:
            return got
    return None
