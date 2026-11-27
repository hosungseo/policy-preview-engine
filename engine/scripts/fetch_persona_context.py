"""Download the KOSIS tables used to give panel members more public-statistics context beyond tenure.

  ../.venv/bin/python scripts/fetch_persona_context.py [table ...]

Raw responses go to data/official/kosis/context/<name>.json (one file per table, chunks concatenated).
pp/life_context.py compiles them into per-person probabilities; nothing here is a fact about a person.
"""
import json
import os
import re
import sys
import time
import urllib.parse

import httpx
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
RAW = ENGINE.parent / "data" / "official" / "kosis" / "context"
OFFICIAL = ENGINE / "series" / "official"


def _key() -> str:
    key = os.environ.get("KOSIS_API_KEY", "").strip()
    if not key:
        raise SystemExit("KOSIS_API_KEY is not set (KOSIS OpenAPI key)")
    return key


def fetch(org: str, tbl: str, prd: str, **objs) -> list[dict]:
    params = {"method": "getList", "apiKey": _key(), "orgId": org, "tblId": tbl, "prdSe": prd, "format": "json",
              "jsonVD": "Y", "itmId": "ALL", **objs}
    if "startPrdDe" not in objs:
        params["newEstPrdCnt"] = "1"
    url = "https://kosis.kr/openapi/Param/statisticsParameterData.do?" + urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=300)
            r.raise_for_status()
            data = json.loads(r.content.decode("utf-8", "replace"))
            break
        except httpx.HTTPError:
            time.sleep(5 * (attempt + 1))
    else:
        raise RuntimeError(f"{tbl}: network")
    if isinstance(data, dict):
        raise RuntimeError(f"{tbl}: {data}")
    time.sleep(1.0)  # KOSIS throttles bursts
    return data


def district_codes(field: str) -> list[str]:
    regions = json.loads((OFFICIAL / "regions.json").read_text(encoding="utf-8"))["districts"]
    return sorted({v[field] for v in regions.values() if v.get(field)})


def chunks(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


# name -> callable returning rows
TABLES = {
    # 2025 registered disabled population, 시군구 × 5-year age, items = total/male/female
    "disability": lambda: fetch("101", "DT_1DP2040", "Y", objL1="ALL", objL2="ALL"),
    # 2025 basic livelihood (general) recipients, 시도 × sex × age
    "livelihood": lambda: fetch("117", "DT_11714_N002", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # 2015 census religion, 시도 × sex × age (2015 is the latest census with religion)
    "religion": lambda: [r for c in ("11", "21", "22", "23", "24", "25", "26", "29", "31", "32", "33", "34", "35",
                                     "36", "37", "38", "39")
                         for r in fetch("101", "DT_1PM1502", "F", objL1=c, objL2="ALL", objL3="ALL")],
    # 2020 census commute mode, 시군구 × sex × age × commute/school
    "commute": lambda: [r for part in chunks(district_codes("kosis2020"), 18)
                        for r in fetch("101", "DT_1PA2003", "F", objL1="+".join(part), objL2="ALL", objL3="ALL",
                                       objL4="ALL")],
    # 2025 community health survey (KCHS), 시군구 crude/standardized rates
    "smoking": lambda: fetch("177", "DT_H_SM", "Y", objL1="ALL"),
    "smoking_male": lambda: fetch("177", "DT_H_SM_MALE", "Y", objL1="ALL"),
    "health_good": lambda: fetch("101", "DT_1YL21011E", "Y", objL1="ALL"),
    # KNHANES national sex × age shape (latest year)
    "knhanes_health": lambda: fetch("177", "DT_11702_N121", "Y", objL1="ALL", objL2="ALL"),
    "knhanes_smoking": lambda: fetch("177", "DT_11702_N001", "Y", objL1="ALL", objL2="ALL"),
    # 2025 household finance and welfare survey
    "income_band": lambda: fetch("101", "DT_1HDAAB03", "Y", objL1="ALL", objL2="ALL"),
    "finance_age": lambda: fetch("101", "DT_1HDAAA06", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "finance_tenure": lambda: fetch("101", "DT_1HDAAA03", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "finance_size": lambda: fetch("101", "DT_1HDAAA04", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "finance_region": lambda: fetch("101", "DT_1HDAAA01", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # chronic disease: KCHS district diagnosis rates (30+) and KNHANES sex × age prevalence shape
    "hypertension": lambda: fetch("177", "DT_HYPER_DOCTOR", "Y", objL1="ALL"),
    "diabetes": lambda: fetch("177", "DT_DIA_DOCTOR", "Y", objL1="ALL"),
    "knhanes_hypertension": lambda: fetch("177", "DT_11702_N105", "Y", objL1="ALL", objL2="ALL"),
    "knhanes_diabetes": lambda: fetch("177", "DT_11702_N102", "Y", objL1="ALL", objL2="ALL"),
    # 2020 census employment status of workers, 시도 × sex × age
    "employment": lambda: [r for c in ("11", "21", "22", "23", "24", "25", "26", "29", "31", "32", "33", "34", "35",
                                       "36", "37", "38", "39")
                           for r in fetch("101", "DT_1PC2006", "F", objL1=c, objL2="ALL", objL3="ALL")],
    # National Pension old-age pension recipients 2025, 시도 × single-year age × sex
    "nps_oldage": lambda: fetch("322", "DT_32202_B049", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # 2024 pension statistics: receipt rates by pension type and age group (65+, 60-64)
    "pension_65": lambda: fetch("101", "DT_1PEN_006", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # net worth quintiles: assets, debt, income by quintile (household finance survey 2025)
    "networth_quintile": lambda: fetch("101", "DT_1HDAAA12", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # dual earners among married households by head age (지역별고용조사, latest half-year)
    "dual_earner": lambda: fetch("101", "DT_1ES4F03S", "Y", objL1="ALL"),
    # non-regular wage workers by sex × age (경제활동인구조사 근로형태별 부가조사)
    "contract": lambda: fetch("101", "DT_1DE7006S", "Y", objL1="ALL", objL2="ALL"),
    # digital: 스마트폰 과의존 실태조사 digital use competence (age groups) + 디지털정보격차 실태조사 older adults
    "digital_use": lambda: fetch("127", "DT_120019N_2021_027", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "digital_gap_elderly": lambda: fetch("127", "DT_12017N0014", "Y", objL1="ALL"),
    # 노인실태조사 2023: functional limitation and care receipt (65+)
    "elder_function": lambda: fetch("117", "DT_117071_C003", "F", objL1="ALL", objL2="ALL"),
    "elder_care": lambda: fetch("117", "DT_117071_C004", "F", objL1="ALL", objL2="ALL"),
    "finance_status": lambda: fetch("101", "DT_1HDAAA09", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "debt_traits": lambda: fetch("101", "DT_1HDAAD01", "Y", objL1="ALL", objL2="ALL"),
    # habits and mental health: KCHS 2025 district rates + KNHANES 2024 sex × age shape
    "drinking": lambda: fetch("177", "DT_117075_H_DR_HIGH_WH", "Y", objL1="ALL"),
    "obesity": lambda: fetch("177", "DT_H_OBE_OBE", "Y", objL1="ALL"),
    "walking": lambda: fetch("177", "DT_H_EX_WALK", "Y", objL1="ALL"),
    "stress": lambda: fetch("177", "DT_H_MENTAL_STRESS", "Y", objL1="ALL"),
    "depression": lambda: fetch("177", "DT_H_MENTAL_DEPRESS", "Y", objL1="ALL"),
    "knhanes_drinking": lambda: fetch("177", "DT_11702_N018", "Y", objL1="ALL", objL2="ALL"),
    "knhanes_obesity": lambda: fetch("177", "DT_11702_N101", "Y", objL1="ALL", objL2="ALL"),
    "knhanes_walking": lambda: fetch("177", "DT_11702_N054", "Y", objL1="ALL", objL2="ALL"),
    "knhanes_stress": lambda: fetch("177", "DT_11702_N061", "Y", objL1="ALL", objL2="ALL"),
    # culture: 국민독서실태조사 2025 (adult reading), 문화향수실태조사 2025 (attended an arts event)
    "reading": lambda: fetch("113", "DT_113_STBL_1029672", "F", objL1="ALL"),
    "arts": lambda: fetch("113", "DT_113_STBL_1026886", "Y", objL1="ALL"),
    # 2025 반려동물 양육 실태조사 (household currently keeps a pet)
    "pet": lambda: fetch("114", "DT_114063_001", "Y", objL1="ALL"),
    # social insurance coverage of wage workers by contract type (근로형태별 부가조사, latest August)
    "social_insurance": lambda: fetch("101", "DT_1DE7081S", "Y", objL1="ALL"),
    # 2025 사회통합실태조사 (KIPA): voicing opinions, voting, isolation, group membership
    "civic_voice": lambda: fetch("417", "DT_417001_0027", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "civic_vote": lambda: fetch("417", "DT_417001_0028", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "civic_isolation": lambda: fetch("417", "DT_417001_0035", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    "civic_groups": lambda: fetch("417", "DT_417001_0021", "Y", objL1="ALL", objL2="ALL", objL3="ALL"),
    # 2025 국민여가활동조사 등 (문화체육관광부): volunteering, overseas travel
    "volunteer": lambda: fetch("113", "DT_113_STBL_1028450", "Y", objL1="ALL"),
    "travel_abroad": lambda: fetch("113", "DT_113_STBL_1029566", "Y", objL1="ALL"),
    # 2024 국민건강영양조사: skipping breakfast
    "breakfast_skip": lambda: fetch("177", "DT_11702_N033", "Y", objL1="ALL", objL2="ALL"),
    # 2023 한국의료패널: private health insurance (persons), unmet hospital care (adults)
    "private_insurance": lambda: fetch("331", "DT_920012N_1072", "Y", objL1="ALL"),
    "unmet_care": lambda: fetch("331", "DT_920012N_2056", "Y", objL1="ALL", objL2="ALL"),
    # 2023 제7차 근로환경조사 (workers): night work, shift work, trouble falling asleep
    "night_work": lambda: fetch("380", "DT_380002_A0561_7TH", "F", objL1="ALL", objL2="ALL"),
    "shift_work": lambda: fetch("380", "DT_380002_A0815_7TH", "F", objL1="ALL", objL2="ALL"),
    "sleep_trouble": lambda: fetch("380", "DT_380002_A0971_7TH", "F", objL1="ALL", objL2="ALL"),
    # 2025 디지털정보격차 실태조사 계열 (과기정통부): can use a kiosk
    "kiosk": lambda: fetch("164", "DT_164004_2025273", "Y", objL1="ALL"),
    # 2023 노인실태조사: senior job program participation
    "senior_job": lambda: fetch("117", "DT_117071_G004", "F", objL1="ALL", objL2="ALL"),
    # 2025 고용형태별 근로실태조사 (고용노동부): union membership, retirement pension by regular/non-regular
    "union_pension": lambda: fetch("118", "DT_118N_LCE310", "Y", objL1="ALL", objL2="ALL"),
    # 2024 청년 삶 실태조사 (국무조정실, 19-34): help when sick, unmet mental care, wish to move to another 시도
    "youth_help": lambda: fetch("170", "DT_170002_F001", "F", objL1="ALL", objL2="ALL", objL3="ALL"),
    "youth_mental_unmet": lambda: fetch("170", "DT_170002_C017", "F", objL1="ALL"),
    "youth_move": lambda: fetch("170", "DT_170002_B034", "F", objL1="ALL", objL2="ALL"),
    # 2023 근로환경조사: weekly hours of the main job, caring for elderly/disabled family, platform self-employment
    "work_hours": lambda: fetch("380", "DT_380002_A08401_7TH", "F", objL1="ALL", objL2="ALL"),
    "worker_care": lambda: fetch("380", "DT_380002_A1002_7TH", "F", objL1="ALL", objL2="ALL"),
    "platform_self": lambda: fetch("380", "DT_380002_A0044_7TH", "F", objL1="ALL", objL2="ALL"),
    # 2024 운전면허 소지자 (경찰청): by single-year age, sex, region (rates use resident population)
    "license_age": lambda: fetch("132", "DT_13201_A002", "Y", objL1="ALL", objL2="ALL"),
    "license_sex": lambda: fetch("132", "DT_13201_A004", "Y", objL1="ALL", objL2="ALL"),
    "license_region": lambda: fetch("132", "DT_13201_A005", "Y", objL1="ALL", objL2="ALL"),
    # ---- multi-year series for life histories (pp/life_history.py) ----
    # 소득이동통계 (국가데이터처, 등록센서스 x 국세청 종단 패널): joint and conditional 5x5 quintile transitions by
    # sex x age, 2018-2024; bottom/top quintile persistence
    "mobility_joint": lambda: fetch("101", "DT_IMEMIA001", "Y", objL1="ALL", objL2="ALL", objL3="ALL",
                                    startPrdDe="2018", endPrdDe="2024"),
    "mobility_cond": lambda: fetch("101", "DT_IMEMIB001", "Y", objL1="ALL", objL2="ALL", objL3="ALL",
                                   startPrdDe="2018", endPrdDe="2024"),
    "mobility_low": lambda: fetch("101", "DT_IMEMID001", "Y", objL1="ALL", startPrdDe="2018", endPrdDe="2024"),
    "mobility_high": lambda: fetch("101", "DT_IMEMID002", "Y", objL1="ALL", startPrdDe="2018", endPrdDe="2024"),
    # 소득이동통계 absolute mobility: distribution of the year-on-year % change in personal labour + business income,
    # 7 categories, by sex x prior-year age x prior-year quintile, 2018-2024
    "income_change": lambda: fetch("101", "DT_IMEMIC001", "Y", objL1="ALL", objL2="ALL", objL3="ALL",
                                   startPrdDe="2018", endPrdDe="2024"),
    # 일자리행정통계 임금근로일자리 소득: mean and median monthly earnings by sex x age band, 2016-2024 (만원)
    "wage_level": lambda: fetch("101", "DT_1EP_2010", "Y", objL1="ALL", objL2="ALL", startPrdDe="2016", endPrdDe="2024"),
    # 지역사회건강조사 current smoking by district, 2018-2025
    "smoking_series": lambda: fetch("177", "DT_H_SM", "Y", objL1="ALL", startPrdDe="2018", endPrdDe="2025"),
    # 경제활동인구조사 employment rate by sex x age, 2017-2025
    "employment_series": lambda: fetch("101", "DT_1DA7012S", "Y", objL1="ALL", objL2="ALL",
                                       startPrdDe="2017", endPrdDe="2025"),
    # 인구이동통계: 시도 origin x destination movers, and interprovincial in-movers by sex x 5-year age (nationwide)
    "migration_od": lambda: fetch("101", "DT_1B26003_A01", "Y", objL1="ALL", objL2="ALL",
                                  startPrdDe="2017", endPrdDe="2025"),
    "migration_age": lambda: [r for y in range(2017, 2026) for r in fetch(
        "101", "DT_1B26001_A04", "Y", objL1="00", objL2="ALL", objL3="ALL", startPrdDe=str(y), endPrdDe=str(y))],
    # 인구동향: marriage and divorce rates per 1,000 of each sex x age, 2017-2025
    "marriage_rate": lambda: fetch("101", "DT_1B83A15", "Y", objL1="ALL", objL2="ALL",
                                   startPrdDe="2017", endPrdDe="2025"),
    "divorce_rate": lambda: fetch("101", "DT_1B85009", "Y", objL1="ALL", objL2="ALL",
                                  startPrdDe="2017", endPrdDe="2025"),
    # 2024 간이생명표 (5-year death probabilities) for forward runs
    "life_table": lambda: fetch("101", "DT_1B41", "Y", objL1="ALL"),
    # repeat movers: 2005 census residence five years earlier (nationwide, sex x age) and 2001-2005 interprovincial
    # in-movers by sex x age, to size the gap between "moved in 5 years" and five single years
    "census2005_residence": lambda: fetch("101", "DT_1MI0501", "F", objL1="00", objL2="ALL", objL3="ALL"),
    "migration_age_2001": lambda: [r for y in range(2001, 2006) for r in fetch(
        "101", "DT_1B26001_A04", "Y", objL1="00", objL2="ALL", objL3="ALL", startPrdDe=str(y), endPrdDe=str(y))],
}


# Pre-2026 codes for districts regions.json lists under their 2026 codes (광주·전남 통합, 인천 개편, 화성 4개 구);
# the December 2025 table still uses these, and build_persona_context.py matches them by name.
OLD_LAWD = ("29110", "29140", "29155", "29170", "29200", "46110", "46130", "46150", "46170", "46230", "46710", "46720",
            "46730", "46770", "46780", "46790", "46800", "46810", "46820", "46830", "46840", "46860", "46870", "46880",
            "46890", "46900", "46910", "28110", "28140", "28260", "41590")


def population(codes: list[str]) -> list[dict]:
    """Resident registration population by 5-year age and sex, December 2025, for the given 행정 (lawd) codes."""
    return [r for part in chunks(codes, 100)
            for r in fetch("101", "DT_1B04005N", "M", objL1="+".join(part), objL2="ALL",
                           startPrdDe="202512", endPrdDe="202512")]


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    names = sys.argv[1:] or [*TABLES, "population"]
    for name in names:
        if name == "population":
            regions = json.loads((OFFICIAL / "regions.json").read_text(encoding="utf-8"))["districts"]
            rows = population(sorted({c["code"] for v in regions.values() for c in v["lawd"]} | set(OLD_LAWD)))
        else:
            rows = TABLES[name]()
        (RAW / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {len(rows)} cells, period {sorted({r['PRD_DE'] for r in rows})}", flush=True)


if __name__ == "__main__":
    main()
