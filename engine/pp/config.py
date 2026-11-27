"""Paths, model names and fixed vocabularies shared by every stage."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class DataMissing(RuntimeError):
    """A required data file (usually on the external SSD) is absent."""


def _env(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def data_dir() -> Path:
    return Path(_env("PP_DATA_DIR", str(REPO_ROOT / "data")))


def persona_db() -> Path:
    override = _env("PP_PERSONA_DB")
    if override:
        return Path(override)
    return data_dir() / "vendor" / "korean-people-persona" / "database" / "persona.db"


def emb_matrix() -> Path:
    return emb_dir() / "emb.f16.npy"


def emb_uuids() -> Path:
    return emb_dir() / "emb_uuids.txt"


def emb_dir() -> Path:
    # A new namespace prevents accidental reuse of retired precomputed vectors.
    return data_dir() / "emb" / "multilingual-e5-large-v1"


def emb_manifest() -> Path:
    return emb_dir() / "manifest.json"


def population_json() -> Path:
    return data_dir() / "population.json"


def occupation_cache(mock: bool = False) -> Path:
    return data_dir() / ("occupation_major.mock.json" if mock else "occupation_major.json")


def llm_cwd() -> Path:
    """Neutral working directory for `claude -p` so no project settings or CLAUDE.md load."""
    path = data_dir() / "llm-cwd"
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir() -> Path:
    return Path(_env("PP_RUNS_DIR", str(REPO_ROOT / "runs")))


def web_runs_dir() -> Path:
    return Path(_env("PP_WEB_RUNS_DIR", str(REPO_ROOT / "web" / "public" / "runs")))


def web_dev_runs_dir() -> Path:
    return Path(_env("PP_WEB_DEV_RUNS_DIR", str(REPO_ROOT / "web" / "dev-runs")))


def web_series_dir() -> Path:
    return Path(_env("PP_WEB_SERIES_DIR", str(REPO_ROOT / "web" / "public" / "series")))


def web_dev_series_dir() -> Path:
    return Path(_env("PP_WEB_DEV_SERIES_DIR", str(REPO_ROOT / "web" / "dev-series")))


FUTURE_YEAR = 2030
REACT_MODEL = _env("PP_REACT_MODEL", "haiku")
SYNTH_MODEL = _env("PP_SYNTH_MODEL", "sonnet")
QUERY_MODEL = "intfloat/multilingual-e5-large"
QUERY_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
EMBEDDING_DIM = 1024
EMBEDDING_TEXT_FORMAT = "e5-query-passage-name-free-v1"

# (low, high, label), inclusive bounds
AGE_BANDS = [
    (19, 29, "19–29세"),
    (30, 39, "30대"),
    (40, 49, "40대"),
    (50, 59, "50대"),
    (60, 69, "60대"),
    (70, 200, "70세 이상"),
]

# Raw province values exactly as stored in Nemotron-Personas-Korea -> display name
PROVINCE_DISPLAY = {
    "서울": "서울", "부산": "부산", "대구": "대구", "인천": "인천", "광주": "광주",
    "대전": "대전", "울산": "울산", "세종": "세종", "경기": "경기", "강원": "강원",
    "충청북": "충북", "충청남": "충남", "전북": "전북", "전라남": "전남",
    "경상북": "경북", "경상남": "경남", "제주": "제주",
}

REGION_OF = {
    "서울": "수도권", "인천": "수도권", "경기": "수도권",
    "대전": "충청권", "세종": "충청권", "충청북": "충청권", "충청남": "충청권",
    "광주": "호남권", "전북": "호남권", "전라남": "호남권",
    "대구": "대경권", "경상북": "대경권",
    "부산": "동남권", "울산": "동남권", "경상남": "동남권",
    "강원": "강원", "제주": "제주",
}
REGIONS = ["수도권", "충청권", "호남권", "대경권", "동남권", "강원", "제주"]

# Household composition (who the person lives with), not eligibility: "자녀와 거주 (한부모)" also covers an older
# widow living with grown-up children, so the group is named by its living arrangement. Results saved before the
# rename carry the old label; LEGACY_FAMILY_LABELS maps it.
CHILDREN_NO_SPOUSE = "배우자 없이 자녀와 거주"
FAMILY_BUCKETS = ["1인 가구", "부부", "부부+자녀", CHILDREN_NO_SPOUSE, "부모 등과 동거", "기타"]
LEGACY_FAMILY_LABELS = {"한부모·자녀": CHILDREN_NO_SPOUSE}
FAMILY_NOTE = ("가구는 함께 사는 사람으로 나눈 가구 구성입니다. 한부모가족 같은 지원 대상인지는 자녀 나이·양육·소득 등 "
               "제도 기준으로 따로 정해지며, 이 이름으로 판단하지 않습니다.")
EDUCATION_ORDER = ["무학", "초등학교", "중학교", "고등학교", "2~3년제 전문대학", "4년제 대학교", "대학원"]
HOUSING_ORDER = ["아파트", "단독주택", "다세대주택", "연립주택", "비주거용 건물 내 주택", "주택 이외의 거처"]
OCCUPATION_MAJORS = [
    "관리자", "전문가 및 관련 종사자", "사무 종사자", "서비스 종사자", "판매 종사자",
    "농림어업 숙련 종사자", "기능원 및 관련 기능 종사자", "장치·기계 조작 및 조립 종사자",
    "단순노무 종사자", "군인", "무직·기타",
]
IMPACTS = ("직접", "간접", "무관")
STANCES = ("우려", "기대", "혼재")

_PROVINCE_ALIASES = {"전라북": "전북"}
_SUFFIXES = ("특별자치도", "특별자치시", "특별시", "광역시", "도")


def age_band(age: int) -> str:
    for low, high, label in AGE_BANDS:
        if low <= int(age) <= high:
            return label
    raise ValueError(f"age out of range: {age}")


def family_bucket(family_type: str) -> str:
    t = family_type.strip()
    if "혼자" in t:
        return "1인 가구"
    if t == "배우자와 거주":
        return "부부"
    if t.startswith("배우자·자녀"):
        return "부부+자녀"
    if t.startswith("배우자"):
        return "기타"
    if t.startswith("자녀"):
        return CHILDREN_NO_SPOUSE
    if any(k in t for k in ("부모", "어머니", "아버지", "부 또는 모", "조부", "조모")):
        return "부모 등과 동거"
    return "기타"


def to_raw_province(name: str) -> str | None:
    n = str(name).strip()
    if n in PROVINCE_DISPLAY:
        return n
    display_to_raw = {v: k for k, v in PROVINCE_DISPLAY.items()}
    if n in display_to_raw:
        return display_to_raw[n]
    for suffix in _SUFFIXES:
        if n.endswith(suffix):
            base = _PROVINCE_ALIASES.get(n[: -len(suffix)], n[: -len(suffix)])
            if base in PROVINCE_DISPLAY:
                return base
            if base in display_to_raw:
                return display_to_raw[base]
    return None
