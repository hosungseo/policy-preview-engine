"""Download the KOSIS tables used to give panel members a tenure (자가·전세·월세) and a home-value band.

  ../.venv/bin/python scripts/fetch_kosis_housing.py

2020 인구주택총조사 (통계청, 5-year cycle, prdSe=F), counts of 일반가구 by 시군구:
  DT_1PE2006  거처의 종류 × 점유형태          (거처 종류 = the persona DB's housing_type categories)
  DT_1PE2010  가구주 연령(5세) × 점유형태
  DT_1PR2008  1인가구 연령(5세) × 점유형태    (성별 계)
2024 주택소유통계 (통계청, yearly), 일반가구 by 거주 시군구:
  DT_1OH0402  주택소유·무주택 가구
  DT_1OH0407  소유 주택 수(1건 … 5건 이상)
  DT_1OH0410  주택자산가액(공시가격 기준) 구간 × 주택소유 가구·소유 주택
Raw responses go to data/official/kosis/<table>.json; compact tables to series/official/census2020_tenure.json and
series/official/ownership2024.json keyed by KOSIS region code (see regions.json for persona districts).
"""
import json
import os
import re
import urllib.parse

import httpx
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
RAW = ENGINE.parent / "data" / "official" / "kosis"
OFFICIAL = ENGINE / "series" / "official"
TENURE = {"자가": "own", "자기집": "own", "전세(월세없음)": "jeonse", "전세(월세 없음)": "jeonse",
          "보증금 있는 월세": "monthly_deposit", "보증금 없는 월세": "monthly_nodeposit", "사글세": "sagulse",
          "무상(관사 사택 등)": "free", "무상": "free"}


def _key() -> str:
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        raise SystemExit("KOSIS_API_KEY is not set (KOSIS OpenAPI key)")
    return key


def fetch(tbl: str, prd: str, **objs) -> list[dict]:
    params = {"method": "getList", "apiKey": _key(), "orgId": "101", "tblId": tbl, "prdSe": prd, "newEstPrdCnt": "1",
              "format": "json", "jsonVD": "Y", **objs}
    url = "https://kosis.kr/openapi/Param/statisticsParameterData.do?" + urllib.parse.urlencode(params)
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
    r.raise_for_status()
    data = json.loads(r.content.decode("utf-8", "replace"))
    if isinstance(data, dict):
        raise RuntimeError(f"{tbl}: {data}")
    RAW.mkdir(parents=True, exist_ok=True)
    (RAW / f"{tbl}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{tbl}: {len(data)} cells, period {sorted({r['PRD_DE'] for r in data})}")
    return data


def num(x: str) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None  # "-" or "..." (suppressed small cells)


def census() -> dict:
    out: dict = defaultdict(lambda: {"housing": defaultdict(dict), "age": defaultdict(dict), "single_age": defaultdict(dict)})
    for r in fetch("DT_1PE2006", "F", itmId="T100", objL1="ALL", objL2="ALL", objL3="ALL"):
        t = TENURE.get(r["C3_NM"])
        v = num(r["DT"])
        if t and v is not None:
            out[r["C1"]]["housing"][r["C2_NM"]][t] = v
    for r in fetch("DT_1PE2010", "F", itmId="ALL", objL1="ALL", objL2="ALL"):
        t = TENURE.get(r["ITM_NM"])
        v = num(r["DT"])
        if t and v is not None:
            out[r["C1"]]["age"][r["C2_NM"]][t] = v
    for r in fetch("DT_1PR2008", "F", itmId="ALL", objL1="ALL", objL2="0", objL3="ALL"):
        t = TENURE.get(r["ITM_NM"])
        v = num(r["DT"])
        if t and v is not None:
            out[r["C1"]]["single_age"][r["C3_NM"]][t] = v
    return {code: {k: dict(v) for k, v in d.items()} for code, d in out.items()}


def ownership() -> dict:
    out: dict = defaultdict(dict)
    for r in fetch("DT_1OH0402", "Y", itmId="ALL", objL1="ALL"):
        v = num(r["DT"])
        if v is not None:
            out[r["C1"]][{"총 가구(일반가구)": "households", "주택소유 가구": "owners", "무주택 가구": "nonowners"}[r["ITM_NM"]]] = v
    for r in fetch("DT_1OH0407", "Y", itmId="ALL", objL1="ALL", objL2="ALL"):
        v = num(r["DT"])
        if v is not None:
            out[r["C1"]].setdefault("homes_owned", {})[r["C2_NM"]] = v
    for r in fetch("DT_1OH0410", "Y", itmId="ALL", objL1="ALL", objL2="ALL", objL3="ALL"):
        v = num(r["DT"])
        if v is not None and r["C3_NM"] == "주택소유 가구":
            out[r["C1"]].setdefault("asset_value", {})[r["C2_NM"]] = v
    return dict(out)


def main() -> None:
    OFFICIAL.mkdir(parents=True, exist_ok=True)
    c = census()
    (OFFICIAL / "census2020_tenure.json").write_text(json.dumps({
        "source": "통계청 2020 인구주택총조사(표본) — KOSIS DT_1PE2006(거처 종류×점유형태), DT_1PE2010(가구주 연령×점유형태), "
                  "DT_1PR2008(1인가구 연령×점유형태, 성별 계)",
        "unit": "일반가구 수", "tenure_keys": sorted(set(TENURE.values())),
        "regions": c}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    o = ownership()
    (OFFICIAL / "ownership2024.json").write_text(json.dumps({
        "source": "통계청 2024 주택소유통계 — KOSIS DT_1OH0402(주택소유·무주택 가구), DT_1OH0407(소유 주택 수), "
                  "DT_1OH0410(주택자산가액 구간, 공시가격 기준)",
        "unit": "일반가구 수(거주지 기준)", "regions": o}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"census regions {len(c)}, ownership regions {len(o)}")


if __name__ == "__main__":
    main()
