"""Map every persona district (e.g. '경기-성남시 분당구') to the codes the housing data sources use.

  ../.venv/bin/python scripts/build_region_codes.py

- lawd: current 5-digit 법정동 시군구 codes for the MOLIT real-transaction APIs (행정안전부 StanReginCd API), each
  optionally with a dong filter ({"code", "umd_in" | "umd_not_in"}). MOLIT re-codes past transactions when districts
  are reorganised: retired codes (e.g. 광주 남구 29155) return nothing even for 2025, while the current codes
  (전남광주통합특별시 남구 12270) return 2025 data (checked 2026-09-25). So every month is queried with current codes.
- kosis2020: 통계청 region code in the 2020 census tables (DT_1PE2010 and siblings)
- kosis2024: 통계청 region code in the 2024 housing-ownership tables (DT_1OH0402 and siblings)

Matching is by province + district name, never by numeric prefix, because province codes changed
(강원 2023, 전북 2024) and districts moved (군위군 경북→대구 2023, 부천시 구 부활 2024).
Writes series/official/regions.json and prints districts it could not match.
"""
import json
import os
import re
import sys
import urllib.parse

import httpx
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pp import personas  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "series" / "official" / "regions.json"
PROVINCE = {
    "서울": ["서울특별시"], "부산": ["부산광역시"], "대구": ["대구광역시"], "인천": ["인천광역시"], "광주": ["광주광역시"],
    "대전": ["대전광역시"], "울산": ["울산광역시"], "세종": ["세종특별자치시"], "경기": ["경기도"],
    "강원": ["강원특별자치도", "강원도"], "충청북": ["충청북도"], "충청남": ["충청남도"],
    "전북": ["전북특별자치도", "전라북도"], "전라남": ["전라남도"], "경상북": ["경상북도"], "경상남": ["경상남도"],
    "제주": ["제주특별자치도"],
}
# Persona districts that no longer exist as one current district (2026 reorganisations).
# 인천 제물포구 = old 동구 (7 법정동 below) + old 중구 inland; 영종구 = old 중구 islands; 서해구 + 검단구 = old 서구;
# 화성시 = its four new districts (2026-02-01).
OLD_DONGGU = ["금곡동", "만석동", "송림동", "송현동", "창영동", "화수동", "화평동"]
REORGANISED = {
    "인천-중구": [{"name": "제물포구", "umd_not_in": OLD_DONGGU}, {"name": "영종구"}],
    "인천-동구": [{"name": "제물포구", "umd_in": OLD_DONGGU}],
    "인천-서구": [{"name": "서해구"}, {"name": "검단구"}],
    "경기-화성시": [{"name": f"화성시 {g}"} for g in ("만세구", "효행구", "병점구", "동탄구")],
}
# 광주광역시 and 전라남도 merged into 전남광주통합특별시 (2026-07-01) keeping district names.
MERGED_PROVINCE = {"광주": "전남광주통합특별시", "전라남": "전남광주통합특별시"}
# The 2020 census predates two changes, so those districts are looked up where they were then.
CENSUS_2020_OVERRIDE = {"대구-군위군": ("경상북", "군위군")}


def _key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        raise SystemExit("DATA_GO_KR_KEY is not set (공공데이터포털 서비스 키)")
    return key


def _kosis_key() -> str:
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        raise SystemExit("KOSIS_API_KEY is not set (KOSIS OpenAPI key)")
    return key


def _get_json(url: str) -> object:
    r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    return json.loads(r.content.decode("utf-8", "replace"))


def lawd_codes() -> dict[tuple[str, str], list[str]]:
    """(province full name, district name) -> current 5-digit 법정동 codes, from StanReginCd."""
    out: dict[tuple[str, str], list[str]] = {}
    page = 1
    while True:
        q = urllib.parse.urlencode({"ServiceKey": _key(), "type": "json", "pageNo": str(page), "numOfRows": "1000"})
        data = _get_json(f"https://apis.data.go.kr/1741000/StanReginCd/getStanReginCdList?{q}")
        body = data["StanReginCd"]
        total = body[0]["head"][0]["totalCount"]
        rows = body[1]["row"] if len(body) > 1 else []
        for r in rows:
            if r["umd_cd"] == "000" and r["ri_cd"] == "00" and r["sgg_cd"] != "000":
                parts = r["locatadd_nm"].split(" ", 1)
                if len(parts) == 1 and parts[0] == "세종특별자치시":
                    parts = [parts[0], "세종시"]  # 세종 has one 시군구 code and no district name
                if len(parts) == 2:
                    out.setdefault((parts[0], parts[1]), []).append(r["region_cd"][:5])
        if page * 1000 >= total:
            return out
        page += 1


def kosis_codes(tbl: str, obj: str, prd_note: str) -> dict[tuple[str, str], str]:
    """(province full name, 'city district' name) -> KOSIS region code, from a table's classification metadata."""
    q = urllib.parse.urlencode({"method": "getMeta", "type": "ITM", "apiKey": _kosis_key(), "orgId": "101", "tblId": tbl,
                                "format": "json", "jsonVD": "Y"})
    items = [it for it in _get_json(f"https://kosis.kr/openapi/statisticsData.do?{q}") if it["OBJ_ID"] == obj]
    name = {it["ITM_ID"]: it["ITM_NM"] for it in items}
    out: dict[tuple[str, str], str] = {}
    for code, nm in name.items():
        if len(code) != 5 or not code.isdigit():
            continue  # 전국, 동부/읍부/면부, 시도 (2 digits)
        province = name.get(code[:2])
        if not province:
            continue
        city = name.get(code[:4] + "0") if code[4] != "0" else None
        full = f"{city} {nm}" if city and city != nm else nm
        out[(province, full)] = code
    print(f"{tbl} ({prd_note}): {len(out)} districts")
    return out


def _lawd(d: str, prov: str, name: str, fulls: list[str], lawd: dict) -> list[dict]:
    """Current 법정동 codes (with dong filters where a reorganised district is split) for a persona district."""
    provinces = [MERGED_PROVINCE[prov]] if prov in MERGED_PROVINCE else fulls
    parts = REORGANISED.get(d, [{"name": name}])
    out = []
    for part in parts:
        codes = next((lawd[(f, part["name"])] for f in provinces if (f, part["name"]) in lawd), None)
        if not codes:
            return []
        out += [{"code": c, **{k: v for k, v in part.items() if k != "name"}} for c in sorted(set(codes))]
    return out


def main() -> None:
    conn = personas.connect()
    districts = [r[0] for r in conn.execute("SELECT DISTINCT district FROM persona ORDER BY district")]
    lawd = lawd_codes()
    k2020 = kosis_codes("DT_1PE2010", "A", "2020 census")
    k2024 = kosis_codes("DT_1OH0402", "SGG", "2024 ownership")
    result, missing = {}, []
    for d in districts:
        prov, name = d.split("-", 1)
        fulls = PROVINCE[prov]
        codes = _lawd(d, prov, name, fulls, lawd)
        p20, n20 = CENSUS_2020_OVERRIDE.get(d, (prov, name))
        if p20 == prov and " " in n20 and n20.startswith("부천시"):
            n20 = "부천시"  # no districts in 부천시 between 2016 and 2024
        c20 = next((k2020[(f, n20)] for f in PROVINCE[p20] if (f, n20) in k2020), None)
        c24 = next((k2024[(f, name)] for f in fulls if (f, name) in k2024), None)
        result[d] = {"lawd": codes, "kosis2020": c20, "kosis2024": c24}
        if not codes or not c20 or not c24:
            missing.append((d, result[d]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"note": "persona district → 법정동 시군구 codes (MOLIT real-transaction APIs) and KOSIS region codes",
                               "sources": {"lawd": "행정안전부 StanReginCd API", "kosis2020": "KOSIS DT_1PE2010 (2020 인구주택총조사)",
                                           "kosis2024": "KOSIS DT_1OH0402 (2024 주택소유통계)"},
                               "districts": result}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(districts)} districts, {len(missing)} with a missing code")
    for d, v in missing:
        print("  ", d, v)


if __name__ == "__main__":
    main()
