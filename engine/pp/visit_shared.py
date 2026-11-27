"""Shared '찾아갈 곳' (venue kinds) and '명단 밖 사람' (ALWAYS_MISSING / PARTIES) logic.

Extracted from `ppservice/survey/visit.py` so both the full survey visit view and the
fast public consultation path (CLI / HTTP API / MCP) use the same fixed venue tables,
missing-person rules, and persona-attribute helpers with zero model calls.
"""
from __future__ import annotations

import re

from . import config

DEFAULT_VENUES = ["행정복지센터", "주민자치회"]
PROVINCE = {"경상남": "경남", "경상북": "경북", "전라남": "전남", "충청남": "충남", "충청북": "충북"}

# The source's '자녀와 거주 (한부모)' is a living arrangement (it includes older parents living with grown-up
# children), not 한부모가족 eligibility, so the group is named by who the person lives with.
CHILDREN_NO_SPOUSE = "배우자 없이 자녀와 사는 사람"
# Labels the 1M roster file may still carry from before a rename (scripts/build_roster_1m.py rebuilds it).
ROSTER_LEGACY = {CHILDREN_NO_SPOUSE: "한부모 가구"}

YOUNG_CHILD = re.compile(r"영유아|어린이집|갓난|신생아|유치원")
CHILD_NEGATION = re.compile(r"(?:자녀|아이|영유아|신생아).{0,12}(?:없|아니)|(?:키우|양육|돌보).{0,5}(?:않|못)|비양육")
CHILD_OTHER_CONTEXT = re.compile(
    r"교사|원장|근무|보육교직원|간호사|실습|봉사|조카|손주|어린 시절|"
    r"(?:어린이집|유치원).{0,8}(?:근처|인근|주변|옆|앞|맞은편)"
)
CHILD_PARENT_CONTEXT = re.compile(
    r"(?:영유아|갓난(?:아기|아이)?|신생아).{0,18}(?:키우|키웁|양육)|"
    r"(?:어린이집|유치원).{0,8}(?:다니는|등원하는).{0,8}(?:자녀|아이|아들|딸)|"
    r"(?:자녀|아이|아들|딸).{0,12}(?:어린이집|유치원).{0,8}(?:보내|등원)|"
    r"(?:어린이집|유치원).{0,4}학부모"
)

# People the synthetic list cannot stand in for. The first three apply to every policy; the rest are named only when
# the policy text mentions them.
ALWAYS_MISSING = [
    {"who": "만 19세 미만", "route": "학교·청소년센터를 통한 의견 듣기"},
    {"who": "외국인 주민(귀화하지 않은 결혼이민자 포함)", "route": "가족센터·외국인주민지원센터, 다국어 안내"},
    {"who": "단체·업계의 조직된 의견", "route": "입법예고 의견 제출, 간담회"},
]

PARTIES = [
    (re.compile(r"다문화|결혼이민|이주민"), "다문화가족·결혼이민자 당사자", "가족센터, 다국어 상담 창구를 통한 대면 면담"),
    (re.compile(r"외국인 ?근로자|이주노동|고용허가"), "외국인 근로자와 고용 사업주", "외국인력지원센터, 사업주 단체"),
    (re.compile(r"청소년|학생|학교"), "학생·청소년 당사자", "학교, 청소년센터, 학생 참여 기구"),
    (re.compile(r"장애"), "장애 당사자와 가족", "장애인복지관, 장애인 단체"),
    (re.compile(r"사업자|업체|영업|가맹|소상공인"), "규제를 받는 사업자", "업종 협회·상인회 간담회"),
    (re.compile(r"농업|어업|농어민|농어촌|축산"), "농어민", "농·수협, 이장단 회의"),
]

AGE_VENUES = {
    "19–29세": ["대학·청년센터", "온라인 설문·누리소통망"],
    "30대": ["직장인 대상 저녁·온라인 간담회", "온라인 설문"],
    "40대": ["학교 학부모회", "직장인 대상 저녁·온라인 간담회"],
    "50대": ["주민자치회", "직능·자영업 단체"],
    "60대": ["주민자치회", "평생학습관"],
    "70세 이상": ["경로당·노인복지관", "방문 면담(온라인 설문은 닿기 어렵습니다)"],
}

# attribute -> (add-on, {value: (label, venue kinds)})
ADDON_GROUPS = {
    "tenure": ("housing", {
        "monthly": ("월세로 사는 사람", ["주거복지센터", "행정복지센터"]),
        "jeonse": ("전세로 사는 사람", ["주거복지센터", "온라인 설문"]),
        "own": ("자기 집에 사는 사람", ["입주자대표회의", "주민자치회"]),
    }),
    "income": ("finance", {
        "lt10": ("가구 연소득 1천만 원 미만", ["행정복지센터 복지 창구", "종합사회복지관"]),
        "ge100": ("가구 연소득 1억 원 이상", ["직능 단체", "온라인 설문"]),
    }),
    "livelihood": ("welfare", {True: ("기초생활보장 수급자", ["행정복지센터 복지 창구", "종합사회복지관"])}),
    "disability": ("welfare", {True: ("등록 장애인", ["장애인복지관", "장애인 단체"])}),
    "basic_pension": ("welfare", {True: ("기초연금을 받는 사람", ["경로당·노인복지관", "행정복지센터"])}),
    "employment": ("work", {
        "self_alone": ("직원 없이 일하는 자영업자", ["상인회", "소상공인지원센터"]),
        "employer": ("직원을 둔 사업주", ["상공회의소·업종 협회", "소상공인지원센터"]),
        "wage": ("임금 근로자", ["직장인 대상 저녁·온라인 간담회", "온라인 설문"]),
    }),
    "nonregular": ("work", {True: ("비정규직 근로자", ["노동권익센터", "고용센터"])}),
    "dual_earner": ("work", {True: ("맞벌이 가구", ["직장인 대상 저녁·온라인 간담회", "어린이집·학교 학부모 모임"])}),
    "digital": ("digital", {"poor": ("인터넷·스마트폰으로 정보 찾기를 어려워하는 사람", ["행정복지센터 방문 창구", "디지털배움터"])}),
    "kiosk_hard": ("digital", {True: ("키오스크 주문·결제를 어려워하는 사람", ["행정복지센터 방문 창구", "경로당·노인복지관"])}),
    "religion": ("belief", {
        "protestant": ("개신교 신자", ["종교 단체 협의 창구"]),
        "buddhist": ("불교 신자", ["종교 단체 협의 창구"]),
        "catholic": ("천주교 신자", ["종교 단체 협의 창구"]),
        "none": ("종교가 없는 사람", DEFAULT_VENUES),
    }),
}

# Domain keyword clues -> fixed venue kinds (never names a specific real organization).
_TOPIC_VENUES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"기초연금|노인|어르신|고령|경로|독거"), ["경로당·노인복지관", "행정복지센터"]),
    (re.compile(r"기초생활|수급자|취약계층|저소득|생계"), ["행정복지센터 복지 창구", "종합사회복지관"]),
    (re.compile(r"도시철도|지하철|시내버스|교통|운수|택시"), ["행정복지센터", "이용 역·정류장 현장 안내 창구"]),
    (re.compile(r"월세|전세|임차|주거|고시원|오피스텔"), ["주거복지센터", "행정복지센터"]),
    (re.compile(r"영유아|어린이집|유치원|보육|육아"), ["어린이집·유치원 학부모 모임", "육아종합지원센터"]),
    (re.compile(r"1인\s*가구|혼자\s*사는|독거"), ["1인가구 지원센터", "행정복지센터"]),
    (re.compile(r"한부모|가족"), ["가족센터", "행정복지센터"]),
    (re.compile(r"비정규|노동|근로|일자리|구직|실업"), ["노동권익센터", "고용센터"]),
    (re.compile(r"디지털|키오스크|모바일|온라인\s*신청"), ["행정복지센터 방문 창구", "디지털배움터"]),
    (re.compile(r"농어촌|농촌|어촌|인구감소|마을"), ["농·수협", "마을회관·이장단 회의"]),
]

VENUE_BASIS_NOTE = "만날 곳은 집단 유형별로 미리 정해 둔 기관 종류이며, 특정 기관을 추천하는 것이 아닙니다."


def header(profile: str) -> dict:
    """The labelled lines at the top of a persona profile ('학력: … / 혼인: …')."""
    out = {}
    for line in (profile or "").split("\n\n")[0].split("\n"):
        for part in line.split(" / "):
            if ": " in part:
                k, v = part.split(": ", 1)
                out[k.strip()] = v.strip()
    return out


def young_child_candidate(profile: str) -> bool:
    """A textual clue for review, never proof of household composition or eligibility."""
    for sentence in re.split(r"[.!?。\n]+", profile or ""):
        if not YOUNG_CHILD.search(sentence) or CHILD_NEGATION.search(sentence):
            continue
        if not CHILD_OTHER_CONTEXT.search(sentence) or CHILD_PARENT_CONTEXT.search(sentence):
            return True
    return False


def _is_capital(p: dict) -> bool:
    if "capital" in p and p["capital"] is not None:
        return bool(p["capital"])
    if p.get("region"):
        return p["region"] == "수도권"
    raw = config.to_raw_province(p.get("province", ""))
    return config.REGION_OF.get(raw or "", "") == "수도권"


def base_groups(p: dict, h: dict | None = None) -> list[tuple[str, str, list[str]]]:
    """(attribute, label, venue kinds) for every base-persona group this person belongs to."""
    h = header(p.get("profile", "")) if h is None else h
    age_band = p.get("age_band") or (config.age_band(int(p["age"])) if p.get("age") is not None else "")
    raw_prov = config.to_raw_province(p.get("province", "")) or p.get("province", "")
    prov_label = PROVINCE.get(raw_prov, raw_prov)
    out = [
        ("연령대", age_band, AGE_VENUES.get(age_band, DEFAULT_VENUES)),
        ("성별", "여성" if p.get("sex") == "여자" else "남성", ["성별을 맞춘 소규모 좌담", "온라인 설문"]),
        ("권역", "수도권 주민" if _is_capital(p) else "비수도권 주민", ["권역별 주민 설명회"]),
        ("시도", f"{prov_label} 주민", ["시도·시군구 주민 설명회", "행정복지센터"]),
    ]
    edu = h.get("학력") or p.get("education_level") or ""
    if edu in ("무학", "초등학교", "중학교"):
        out.append(("학력", "중학교 졸업 이하", ["쉬운 말 자료를 쓴 대면 설명회", "행정복지센터"]))
    elif edu in ("4년제 대학교", "대학원"):
        out.append(("학력", "대학 졸업 이상", ["온라인 설문", "직장인 대상 저녁·온라인 간담회"]))
    marital = h.get("혼인") or p.get("marital_status") or ""
    if marital == "미혼":
        out.append(("혼인", "미혼", ["대학·청년센터", "온라인 설문·누리소통망"]))
    elif marital == "사별":
        out.append(("혼인", "배우자와 사별한 사람", ["경로당·노인복지관", "방문 면담"]))
    elif marital == "이혼":
        out.append(("혼인", "이혼한 사람", ["가족센터", "행정복지센터"]))
    household = h.get("가구") or p.get("family_type") or ""
    if household.startswith("혼자 거주"):
        out.append(("가구", "혼자 사는 사람", ["1인가구 지원센터", "행정복지센터"]))
    elif "한부모" in household:
        out.append(("가구", CHILDREN_NO_SPOUSE, ["가족센터", "행정복지센터"]))
    if young_child_candidate(p.get("profile", "")):
        out.append(("영유아", "영유아·보육 관련 언급 인물(확인 후보)", ["어린이집·유치원 학부모 모임", "육아종합지원센터"]))
    housing = h.get("주거") or p.get("housing_type") or ""
    if housing == "아파트":
        out.append(("주택", "아파트에 사는 사람", ["입주자대표회의", "관리사무소 게시판"]))
    elif housing == "단독주택":
        out.append(("주택", "단독주택에 사는 사람", ["통·반장 회의", "마을회관"]))
    elif housing == "주택 이외의 거처":
        out.append(("주택", "오피스텔·고시원 등 주택이 아닌 곳에 사는 사람", ["주거복지센터", "행정복지센터"]))
    occupation = h.get("직업") or p.get("occupation") or ""
    if occupation == "무직":
        out.append(("일", "일을 하지 않는 사람", ["고용센터", "행정복지센터"]))
    return out


def missing_people(text: str) -> list[dict]:
    """People the synthetic list cannot stand in for: policy-named parties first, then always-missing groups."""
    text = text or ""
    missing = [{"who": who, "route": route, "party": True} for pattern, who, route in PARTIES if pattern.search(text)]
    missing += [{**item, "party": False} for item in ALWAYS_MISSING]
    return missing


def _add_unique(target: list[str], items: list[str], limit: int = 4) -> None:
    for item in items:
        if len(target) >= limit:
            return
        text = str(item or "").strip()
        if text and text not in target:
            target.append(text)


def _age_venues_for_range(age_min: int | None, age_max: int | None) -> list[str]:
    if age_min is None and age_max is None:
        return []
    lo = 19 if age_min is None else age_min
    hi = 100 if age_max is None else age_max
    out: list[str] = []
    # Older adults (65+) need offline-friendly venues such as 경로당·노인복지관.
    if hi >= 65 and lo >= 60:
        _add_unique(out, ["경로당·노인복지관", "방문 면담(온라인 설문은 닿기 어렵습니다)"], limit=3)
    for band_lo, band_hi, label in config.AGE_BANDS:
        if band_hi >= lo and band_lo <= hi:
            _add_unique(out, AGE_VENUES.get(label, DEFAULT_VENUES), limit=3)
    return out


def _venues_from_condition(condition: dict | None, group_name: str) -> list[str]:
    venues: list[str] = []
    cond = condition or {}
    # 1. Party & domain keyword clues from condition name, keywords, eligibility, occupations
    clue_text = " ".join([
        group_name,
        *(cond.get("keywords") or []),
        *(cond.get("eligibility") or []),
        *(cond.get("occupations") or []),
    ])
    for pattern, _who, route in PARTIES:
        if pattern.search(clue_text):
            _add_unique(venues, [part.strip() for part in route.split(",")], limit=4)
    if re.search(r"(?:도시철도|지하철).{0,10}(?:미운행|없는)", clue_text):
        _add_unique(venues, ["행정복지센터", "마을회관·시내버스 안내 창구"], limit=4)
    for pattern, items in _TOPIC_VENUES:
        if pattern.pattern.startswith("도시철도") and re.search(r"(?:도시철도|지하철).{0,10}(?:미운행|없는)", clue_text):
            continue
        if pattern.search(clue_text):
            _add_unique(venues, items, limit=4)
    # 2. Age range
    _add_unique(venues, _age_venues_for_range(cond.get("age_min"), cond.get("age_max")), limit=4)
    # 3. Household / housing / education filters
    for fam in cond.get("family_type_like") or []:
        if "혼자" in fam:
            _add_unique(venues, ["1인가구 지원센터", "행정복지센터"], limit=4)
        elif "한부모" in fam:
            _add_unique(venues, ["가족센터", "행정복지센터"], limit=4)
    for house in cond.get("housing_type_in") or []:
        if house == "아파트":
            _add_unique(venues, ["입주자대표회의", "관리사무소 게시판"], limit=4)
        elif house == "단독주택":
            _add_unique(venues, ["통·반장 회의", "마을회관"], limit=4)
        elif house == "주택 이외의 거처":
            _add_unique(venues, ["주거복지센터", "행정복지센터"], limit=4)
    if any(e in ("무학", "초등학교", "중학교") for e in (cond.get("education_in") or [])):
        _add_unique(venues, ["쉬운 말 자료를 쓴 대면 설명회", "행정복지센터"], limit=4)
    # 4. Provinces
    provs = [config.PROVINCE_DISPLAY.get(p, p) for p in (cond.get("provinces") or [])]
    if provs and len(venues) < 4:
        region_hint = f"{'·'.join(provs[:3])} 지역 행정복지센터·주민 설명회"
        _add_unique(venues, [region_hint, "시도·시군구 주민자치회"], limit=4)
    return venues


def _venues_from_members(people: list[dict], limit: int = 4) -> tuple[list[str], list[str]]:
    """Derive venues and cautions from members' base persona attributes without counts or rankings."""
    if not people:
        return [], []
    # Fixed priority order for attributes that indicate concrete access venues (no vote or count ordering).
    specific_attrs = ("연령대", "가구", "학력", "영유아", "주택", "일", "혼인")
    member_sets: list[set[tuple[str, str]]] = []
    venue_by_key: dict[tuple[str, str], list[str]] = {}
    cautions: list[str] = []
    for p in people:
        keys: set[tuple[str, str]] = set()
        for attr, label, vs in base_groups(p):
            if attr in specific_attrs:
                keys.add((attr, label))
                venue_by_key.setdefault((attr, label), vs)
                if attr == "가구" and config.FAMILY_NOTE not in cautions:
                    cautions.append(config.FAMILY_NOTE)
        member_sets.append(keys)
    venues: list[str] = []
    # Attributes shared by every member in the group come first.
    shared = set.intersection(*member_sets) if member_sets else set()
    for attr in specific_attrs:
        for k_attr, label in sorted(shared):
            if k_attr == attr:
                _add_unique(venues, venue_by_key[(k_attr, label)], limit=limit)
    # Only fall back to individual access-barrier clues when the group has no shared attribute venues.
    if not venues:
        barrier_keys = [
            ("연령대", "70세 이상"),
            ("학력", "중학교 졸업 이하"),
            ("가구", "혼자 사는 사람"),
            ("가구", CHILDREN_NO_SPOUSE),
            ("주택", "오피스텔·고시원 등 주택이 아닌 곳에 사는 사람"),
            ("주택", "단독주택에 사는 사람"),
            ("일", "일을 하지 않는 사람"),
            ("영유아", "영유아·보육 관련 언급 인물(확인 후보)"),
        ]
        present = set.union(*member_sets) if member_sets else set()
        for key in barrier_keys:
            if key in present and len(venues) < limit:
                _add_unique(venues, venue_by_key[key], limit=limit)
    return venues, cautions


def _method_for_venues(venues: list[str], channels: list[str]) -> str:
    primary = " ".join(venues[:2])
    if any(k in primary for k in ("복지 창구", "종합사회복지관")):
        return "행정복지센터 복지 창구·복지관 연계 개별 면담과 안내문 설명"
    if any(k in primary for k in ("장애인복지관", "장애인 단체")):
        return "장애인복지관·당사자 단체와 연계한 접근성 보장 대면 면담"
    if any(k in primary for k in ("가족센터", "외국인", "다국어")):
        return "가족센터 연계 다국어 안내와 대면 상담 창구 운영"
    if any(k in primary for k in ("농·수협", "이장단", "마을회관", "통·반장")):
        return "마을회관·이장단 회의 방문 설명과 현장 질의응답"
    if any(k in primary for k in ("상인회", "업종 협회", "소상공인", "직능")):
        return "상인회·직능 단체 경유 소규모 현장 간담회"
    if any(k in primary for k in ("어린이집", "유치원", "학부모", "육아종합지원센터")):
        return "어린이집·학교 학부모 모임 연계 짧은 현장 의견 청취"
    if any(k in primary for k in ("대학·청년센터", "누리소통망")):
        return "청년센터 소규모 간담회와 온라인 의견 창구 병행"
    if any(k in primary for k in ("직장인 대상 저녁",)):
        return "퇴근 이후 저녁·온라인 간담회와 짧은 비대면 의견 접수"
    if any(k in primary for k in ("경로당", "노인복지관", "방문 면담", "쉬운 말")):
        return "쉬운 말 자료를 활용한 방문 면담과 대면 설명회(온라인 설문만으로 닿기 어려움)"
    if any(k in primary for k in ("1인가구", "주거복지센터", "고용센터", "노동권익센터")):
        return "지역 지원센터 창구 연계 개별 면담과 비대면 접수 병행"
    if any(k in primary for k in ("평생학습관",)):
        return "평생학습관·주민자치회 대면 설명회와 현장 짧은 질의응답"
    return "행정복지센터·주민자치회 대면 설명회와 현장 짧은 질의응답"


def _question_for_venues(group_name: str, venues: list[str], condition: dict | None) -> str:
    joined = " ".join([group_name] + venues[:2])
    if any(k in joined for k in ("복지 창구", "기초연금", "기초생활", "취약계층", "수급자")):
        return "본인이 대상에 해당하는지 확인하고 신청하는 과정에서 어떤 안내가 필요한가요?"
    if any(k in joined for k in ("미운행", "시내버스", "마을회관", "농·수협", "이장단", "농어촌")):
        return "지역 현장에서 이 정책을 접하고 이용·신청하는 데 어떤 이동·절차 부담이 있나요?"
    if any(k in joined for k in ("도시철도", "지하철", "이용 역")):
        return "요금이나 기준이 바뀔 때 일상 이동과 역·창구 이용에서 어떤 점이 가장 달라지나요?"
    if any(k in joined for k in ("상인회", "업종 협회", "소상공인", "사업자", "직능")):
        return "현장 영업과 운영 절차에서 먼저 부딪히는 기준이나 준비 사항이 무엇인가요?"
    if any(k in joined for k in ("대학·청년센터", "직장인 대상 저녁", "학부모")):
        return "일과 시간 외에 의견을 내거나 정책 변경 내용을 확인하기 편한 통로는 어디인가요?"
    if any(k in joined for k in ("경로당", "노인복지관", "방문 면담", "쉬운 말")):
        return "안내 내용을 이해하기 어렵거나 방문·신청 과정에서 막히는 절차가 무엇인가요?"
    if any(k in joined for k in ("1인가구", "주거복지센터", "가족센터")):
        return "생활 여건에 맞는 안내를 어디서 접하며, 의견을 내는 데 어떤 걸림돌이 있나요?"
    if condition and condition.get("provinces"):
        return "지역 주민 입장에서 이 정책의 적용 범위와 현장 지원 창구가 분명하게 전달되나요?"
    return "현장에서 이 정책의 내용을 확인하고 의견을 전달할 때 어떤 통로가 접근하기 쉽나요?"


def venue_guidance(
    group_name: str,
    people: list[dict],
    *,
    reactions: list[dict] | None = None,
    condition: dict | None = None,
) -> dict:
    """Build concrete outreach guidance for one group from visit.py tables + reaction channels.

    Never counts, scores, or ranks members; returns only venue kinds, channels, method, and cautions.
    """
    venues = _venues_from_condition(condition, group_name)
    member_venues, cautions = _venues_from_members(people, limit=4)
    if len(venues) < 3:
        _add_unique(venues, member_venues, limit=4)
    if not venues:
        venues = list(DEFAULT_VENUES)

    channels: list[str] = []
    for r in reactions or []:
        ch = str(r.get("channel") or "").strip()
        if ch and ch != "없음" and ch not in channels:
            channels.append(ch)
            if len(channels) >= 4:
                break

    method = _method_for_venues(venues, channels)
    where_parts = list(venues)
    if channels:
        where_text = f"{' · '.join(where_parts)} (반응 언급 접점: {', '.join(channels)})"
    else:
        where_text = " · ".join(where_parts)
    question = _question_for_venues(group_name, venues, condition)

    return {
        "group": group_name,
        "venues": venues,
        "channels": channels,
        "method": method,
        "where": where_text,
        "question": question,
        "cautions": cautions,
        "basis": VENUE_BASIS_NOTE,
    }
