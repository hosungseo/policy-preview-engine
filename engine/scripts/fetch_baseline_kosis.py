"""Collect explicitly dated social-survey tables or use an offline --fixture.

Usage: fetch_baseline_kosis.py --year 2024 --out /path/to/official.json
The fixture is a JSON object keyed by table ID containing raw KOSIS rows.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse

import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_kosis_housing import _key  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "baseline_official.json"
ITEMS = [
    {"id": "marriage", "tbl": "DT_1SSFA060R", "title": "결혼에 대한 견해",
     "question": "결혼에 대한 귀하의 견해는 어떻습니까?",
     "options": ["반드시 해야 한다", "하는 것이 좋다", "해도 좋고 하지 않아도 좋다", "하지 않는 것이 좋다", "하지 말아야 한다", "잘 모르겠다"]},
    {"id": "remarriage", "tbl": "DT_1SSFA080R", "title": "재혼에 대한 견해",
     "question": "재혼에 대한 귀하의 견해는 어떻습니까?", "options": None},
    {"id": "safety_crime", "tbl": "DT_1SSSA020R", "title": "사회안전 인식(범죄)",
     "question": "우리 사회가 범죄로부터 얼마나 안전하다고 생각하십니까?", "options": None},
    {"id": "safety_disaster", "tbl": "DT_1SSSA012R", "title": "사회안전 인식(자연재해)",
     "question": "우리 사회가 자연재해로부터 얼마나 안전하다고 생각하십니까?", "options": None},
    {"id": "safety_security", "tbl": "DT_1SSSA011R", "title": "사회안전 인식(국가 안보 문제)",
     "question": "우리 사회가 국가 안보 문제로부터 얼마나 안전하다고 생각하십니까?", "options": None},
]
SAFETY_ORDER = ["매우 안전", "비교적 안전", "보통", "비교적 안전하지 않음", "매우 안전하지 않음"]
AGE_ROWS = {"20∼29세": "20–29세", "30∼39세": "30대", "40∼49세": "40대", "50∼59세": "50대", "60∼69세": "60대",
            "70세이상": "70세 이상", "70세 이상": "70세 이상", "60세이상": "60세 이상", "60세 이상": "60세 이상"}
SEX_ROWS = {"- 남자": "남자", "- 여자": "여자", "남자": "남자", "여자": "여자"}


def fetch(tbl: str, year: int = 2024) -> list[dict]:
    url = "https://kosis.kr/openapi/Param/statisticsParameterData.do?" + urllib.parse.urlencode({
        "method": "getList", "apiKey": _key(), "orgId": "101", "tblId": tbl, "itmId": "ALL", "objL1": "ALL",
        "objL2": "ALL", "objL3": "", "format": "json", "jsonVD": "Y", "prdSe": "F", "startPrdDe": str(year), "endPrdDe": str(year)})
    try:
        response = httpx.get(url, timeout=60)
        response.raise_for_status()
        data = response.json()
    except Exception:
        raise ValueError("KOSIS request failed") from None
    if isinstance(data, dict):
        raise ValueError("KOSIS response rejected")
    validate_year(data, year)
    return data


def validate_year(rows: list[dict], year: int) -> None:
    if not rows or any(str(r.get("PRD_DE")) != str(year) for r in rows):
        raise ValueError("year_mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-out", type=Path, help="Archive original KOSIS rows for reproducible review")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text()) if args.fixture else None
    out = {"source": f"통계청 「{args.year} 사회조사」(KOSIS, 13세 이상 인구, %) — 성별·전국은 13세 이상 참고값, 성인 점수에서 제외",
           "items": []}
    raw_tables = {}
    for item in ITEMS:
        raw = fixture[item["tbl"]] if fixture is not None else fetch(item["tbl"], args.year)
        raw_tables[item['tbl']] = raw
        validate_year(raw, args.year)
        rows = [r for r in raw if r["C1_NM"] == "전국"]
        period = rows[0]["PRD_DE"]
        names = [n for n in dict.fromkeys(r["ITM_NM"] for r in rows) if n != "계"]
        options = item["options"] or (SAFETY_ORDER if set(SAFETY_ORDER) <= set(names) else names)
        if set(options) != set(names):
            raise SystemExit(f"{item['tbl']}: options {names} != {options}")
        groups: dict[str, dict] = {}
        for r in rows:
            c2 = r.get("C2_NM", "")
            label = "전국" if c2 == "계" else AGE_ROWS.get(c2) or SEX_ROWS.get(c2)
            if not label or r["ITM_NM"] == "계":
                continue
            groups.setdefault(label, {})[r["ITM_NM"]] = round(float(r["DT"]), 2)
        bands = sorted(k for k in groups if k not in ("전국", "남자", "여자"))
        if '60대' in bands:
            bands.remove('60세 이상')
        out["items"].append({**{k: item[k] for k in ("id", "tbl", "title", "question")}, "period": period,
                             "options": options, "groups": groups, "age_bands": bands,
                             "definition": {"year": args.year, "unit": "adult_person", "min_age": 20, "max_age": None,
                                            "population": "20세 이상 개인", "survey_mode": "확인 필요",
                                            "survey_date": "확인 필요", "policy_context": None,
                                            "sex_eligible": False, "fixed_weights": None},
                             "excluded_reasons": ["fixed_weights_missing", "sex_adult_cross_table_missing"],
                             "group_definitions": {g: {"min_age": 13 if g in ("전국", "남자", "여자") else int(g[:2]),
                                                       "max_age": None if g.endswith("이상") or g in ("전국", "남자", "여자") else int(g[:2]) + 9,
                                                       "population": "20세 이상 개인" if g not in ("전국", "남자", "여자") else "13세 이상 개인",
                                                       "options": options,
                                                       "unit": "adult_person" if g not in ("전국", "남자", "여자") else "person", "year": args.year,
                                                       "eligible": g not in ("전국", "남자", "여자")} for g in groups}})
        print(item["tbl"], period, len(options), "options;", "groups:", sorted(groups))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.raw_out:
        args.raw_out.parent.mkdir(parents=True, exist_ok=True)
        args.raw_out.write_text(json.dumps(raw_tables, ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == "__main__":
    sys.exit(main())
