"""Shared fixtures: a tiny persona DB with the real schema (incl. FTS5 trigram)."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ppservice.survey.panel import BUNDLE as PANEL_BUNDLE  # noqa: E402

# Tests marked needs_panel read the 20k panel bundle, which is built locally and not kept in git.
NO_PANEL = "2만 명 패널 묶음 없음: engine/scripts/build_panel_from_nemotron.py로 만드세요"


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_panel: needs engine/ppservice/data/panel-20k.jsonl.gz (skipped when absent)")


def pytest_collection_modifyitems(config, items):
    if PANEL_BUNDLE.exists():
        return
    skip = pytest.mark.skip(reason=NO_PANEL)
    for item in items:
        if "needs_panel" in item.keywords:
            item.add_marker(skip)

PROVINCES = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
             "충청북", "충청남", "전북", "전라남", "경상북", "경상남", "제주"]
OCCUPATIONS = ["택시 운전원", "초등학교 교사", "곡물 재배자", "소규모 상점 경영자", "사무 보조원",
               "무직", "하역 및 적재 관련 단순 종사원", "간호사", "소프트웨어 개발자", "요양보호사"]
FAMILY = ["혼자 거주", "배우자와 거주", "배우자·자녀와 거주", "자녀와 거주 (한부모)", "부모와 동거", "기타2세대"]
HOUSING = ["아파트", "단독주택", "다세대주택", "연립주택", "주택 이외의 거처", "비주거용 건물 내 주택"]
EDU = ["무학", "초등학교", "중학교", "고등학교", "2~3년제 전문대학", "4년제 대학교", "대학원"]
NAMES = ["김영숙", "이정훈", "박지영", "최민수", "정순자", "강현우", "조은비", "윤태식", "장미란", "임도윤"]
TEXT_COLS = ["persona", "professional_persona", "sports_persona", "arts_persona", "travel_persona",
             "culinary_persona", "family_persona", "cultural_background", "skills_and_expertise",
             "hobbies_and_interests", "career_goals_and_ambitions"]
FTS_COLS = TEXT_COLS[1:]


def make_rows(n: int = 170) -> list[dict]:
    rows = []
    for i in range(n):
        prov = PROVINCES[i % len(PROVINCES)]
        age = 19 + (i * 7) % 72
        occ = OCCUPATIONS[i % len(OCCUPATIONS)]
        name = NAMES[i % len(NAMES)]
        commute = "매일 지하철로 출퇴근하며" if i % 3 == 0 else "동네 버스를 타고 다니며"
        row = {c: "" for c in TEXT_COLS}
        row.update(
            id=i + 1, uuid=f"u{i + 1:05d}",
            persona=f"{name} 씨는 {prov}에 사는 {age}세 {occ}입니다.",
            professional_persona=f"{name} 씨는 {occ}로 일하며 {commute} 성실하게 생활합니다.",
            family_persona=f"{name} 씨는 가족과 함께 지냅니다.",
            cultural_background=f"{prov}에서 자랐습니다.",
            sex="여자" if i % 2 else "남자", age=age,
            marital_status="배우자있음" if i % 4 else "미혼",
            family_type=FAMILY[i % len(FAMILY)], housing_type=HOUSING[i % len(HOUSING)],
            education_level=EDU[i % len(EDU)], bachelors_field="해당없음", occupation=occ,
            district=f"{prov}-중구", province=prov,
        )
        rows.append(row)
    return rows


@pytest.fixture(autouse=True)
def no_real_jev_cache(monkeypatch):
    """Tests never read or write the on-disk Jev cache unless they opt in."""
    monkeypatch.setenv("PP_JEV_CACHE", "0")


@pytest.fixture(autouse=True)
def default_upstage_endpoint(monkeypatch):
    """A region or base URL set in the developer's shell must not change which endpoint the tests expect."""
    monkeypatch.delenv("UPSTAGE_BASE_URL", raising=False)
    monkeypatch.delenv("PP_UPSTAGE_REGION", raising=False)


@pytest.fixture
def persona_db(tmp_path, monkeypatch):
    path = tmp_path / "persona.db"
    conn = sqlite3.connect(path)
    cols = ["id INTEGER PRIMARY KEY", "uuid TEXT"] + [f"{c} TEXT" for c in TEXT_COLS] + [
        "sex TEXT", "age INTEGER", "marital_status TEXT", "family_type TEXT", "housing_type TEXT",
        "education_level TEXT", "bachelors_field TEXT", "occupation TEXT", "district TEXT", "province TEXT"]
    conn.execute(f"CREATE TABLE persona ({', '.join(cols)})")
    rows = make_rows()
    keys = list(rows[0].keys())
    conn.executemany(
        f"INSERT INTO persona ({','.join(keys)}) VALUES ({','.join('?' * len(keys))})",
        [tuple(r[k] for k in keys) for r in rows],
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE persona_fts USING fts5({', '.join(FTS_COLS)}, "
        "content='persona', content_rowid='id', tokenize='trigram')"
    )
    conn.execute(f"INSERT INTO persona_fts(rowid, {', '.join(FTS_COLS)}) SELECT id, {', '.join(FTS_COLS)} FROM persona")
    conn.commit()
    conn.close()
    monkeypatch.setenv("PP_PERSONA_DB", str(path))
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path / "data"))
    return path
