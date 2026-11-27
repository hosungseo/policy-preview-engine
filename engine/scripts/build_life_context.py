"""Assign life context (pp/life_context.py) to the service's 20k panel and check it against official numbers.

  ../.venv/bin/python scripts/build_life_context.py

Writes ppservice/data/persona-context/life-context-v2.jsonl.gz (one assignment per uuid) and report-v2.json
(raking gaps, panel shares vs official, held-out checks the assignment never used).
"""
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from pp import life_context, personas  # noqa: E402
from ppservice.survey import panel  # noqa: E402

OUT = ENGINE / "ppservice" / "data" / "persona-context"
DB_SQL = ("SELECT uuid, family_type, occupation, education_level, housing_type, marital_status, district"
          " FROM persona WHERE uuid IN (SELECT value FROM json_each(?))")
# Band midpoints (만원) for comparing a mean; the open top band uses the survey's 1억+ mean, roughly 1.6억.
MIDPOINT = life_context.INCOME_MIDPOINT
REGION_NAME = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시", "광주": "광주광역시",
               "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시", "경기": "경기도", "강원": "강원특별자치도",
               "충청북": "충청북도", "충청남": "충청남도", "전북": "전북특별자치도", "전라남": "전라남도", "경상북": "경상북도",
               "경상남": "경상남도", "제주": "제주특별자치도"}


def load_people() -> list[dict]:
    people, _ = panel.load(addons="off")
    conn = personas.connect()
    extra = {}
    uuids = [p["uuid"] for p in people]
    for i in range(0, len(uuids), 900):
        part = uuids[i:i + 900]
        for r in conn.execute(DB_SQL, (json.dumps(part),)):
            extra[r["uuid"]] = dict(r)
    return [{**p, **extra[p["uuid"]], "age": int(p["age"])} for p in people]


def pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


MARITAL = {"미혼": "(가구주 혼인상태) 미혼", "배우자있음": "(가구주 혼인상태) 배우자 있음",
           "사별": "(가구주 혼인상태) 사별", "이혼": "(가구주 혼인상태) 이혼"}


def held_out(rows: list[dict], by_uuid: dict, t: dict) -> dict:
    """Income-band shares by head sex and head marital status: published, but never given to the raking."""
    inc = t["finance"]["income_band"]
    groups: dict = defaultdict(list)
    for r in rows:
        p = by_uuid[r["uuid"]]
        if "income" not in r or not life_context.is_head(p):
            continue
        groups["(가구주 성) " + p["sex"]].append(r["income"])
        m = MARITAL.get((p.get("marital_status") or "").replace(" ", ""))
        if m:
            groups[m].append(r["income"])
    out = {}
    for key, bands in sorted(groups.items()):
        panel_share = {b: round(bands.count(b) / len(bands), 4) for b in life_context.INCOME_BANDS}
        official = inc[key]
        out[key] = {"n": len(bands), "panel": panel_share, "official": official,
                    "max_gap": round(max(abs(panel_share[b] - official[b]) for b in panel_share), 4),
                    "panel_mean": round(sum(MIDPOINT[b] for b in bands) / len(bands)),
                    "official_mean": round(sum(MIDPOINT[b] * official[b] for b in official))}
    return out


def arts_held_out(rows: list[dict], by_uuid: dict, t: dict) -> dict:
    """Arts attendance by work status and disability registration (both raking targets)."""
    groups: dict = defaultdict(list)
    for r in rows:
        if "arts" not in r:
            continue
        key = {"wage": "상용근로자", "self_alone": "고용원이 없는 자영업자", "employer": "고용원이 있는 자영업자",
               "family": "무급가족종사자"}.get(r.get("employment"))
        if r.get("employment") == "wage" and r.get("nonregular"):
            key = "임시근로자"
        if (by_uuid[r["uuid"]].get("occupation") or "") in life_context.NO_JOB:
            key = "해당없음(무직)"
        if key:
            groups[key].append(r["arts"])
        groups["장애등록" if r.get("disability") else "해당사항없음"].append(r["arts"])
    return {k: {"n": len(v), "panel": round(sum(v) / len(v), 3), "official": t["arts"].get(k)} for k, v in sorted(groups.items())}


def catalog(rows: list[dict], by_uuid: dict) -> dict:
    """Add-on catalog for the product: what each module adds, from which surveys, and how many panel members get a
    line from it."""
    t = life_context.tables()
    out = {"version": life_context.VERSION, "panel": len(rows),
           "note": "기본 = NVIDIA Nemotron-Personas-Korea 프로필. 애드온 = 공표된 정부 조사·행정 통계로 배정한 생활 여건(통계적 가정).",
           "addons": {}}
    for name, spec in life_context.ADDONS.items():
        covered = [r for r in rows if life_context._lines(name, r)]
        example = next((life_context._lines(name, r) for r in rows if len(life_context._lines(name, r)) >= 1), [])
        out["addons"][name] = {**spec, "covered_people": len(covered),
                               "covered_share": round(len(covered) / len(rows), 3), "example_lines": example}
    out["sources_detail"] = t["sources"]
    return out


def main() -> None:
    people = load_people()
    assigned, diag = life_context.build(people)
    t = life_context.tables()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [{"uuid": p["uuid"], **assigned[p["uuid"]]} for p in people]
    blob = "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows) + "\n"
    (OUT / "life-context-v2.jsonl.gz").write_bytes(gzip.compress(blob.encode("utf-8"), mtime=0))

    n = len(people)
    by_uuid = {p["uuid"]: p for p in people}

    def share(attr: str, value=True, subset=None) -> float | None:
        pool = [r for r in rows if r.get(attr) is not None and (subset is None or subset(by_uuid[r["uuid"]], r))]
        return round(sum(1 for r in pool if r[attr] == value) / len(pool), 4) if pool else None

    # held-out 1: mean household income by province (income raking never saw region)
    region = defaultdict(list)
    tenure_inc = defaultdict(list)
    for r in rows:
        if "income" in r:
            region[by_uuid[r["uuid"]]["province"]].append(MIDPOINT[r["income"]])
            tenure_inc[r["tenure"]].append(MIDPOINT[r["income"]])
    official_region = t["finance"]["mean_income_by_region"]
    reg_rows = [(p, round(sum(v) / len(v)), official_region[REGION_NAME[p]]) for p, v in sorted(region.items())]
    tenure_key = {"own": "자기집", "jeonse": "전세", "monthly": "월세", "free": "기타"}
    ten_rows = [(k, round(sum(v) / len(v)), t["finance"]["mean_income_by_tenure"][tenure_key[k]])
                for k, v in sorted(tenure_inc.items())]
    report = {
        "value_schema": diag["value_schema"], "finance_unit": diag["finance_unit"], "limitations": diag["limitations"],
        "addon_rake_gap": diag["addon_rake_gap"],
        "version": life_context.VERSION, "people": n, "rake_gap": diag["rake_gap"],
        "skipped_by_profile_text": dict(Counter(s for r in rows for s in r["skipped"])),
        "panel_vs_official": {
            "income_band": {"panel": {b: round(sum(1 for r in rows if r.get("income") == b) /
                                               sum(1 for r in rows if "income" in r), 4)
                                      for b in life_context.INCOME_BANDS},
                            "official_households": t["finance"]["income_band"]["전체"]},
            "debt": {"panel": share("debt"), "official_households": t["finance"]["debt_holding"]["전체"]},
            "car": {"panel": share("car"), "official_households": t["finance"]["car_by_age"]["전체"]},
            "livelihood_19plus": {"panel": share("livelihood")},
            "disability_19plus": {"panel": share("disability")},
            "religion": {"panel": dict(Counter(r["religion"] for r in rows if "religion" in r))},
            "commute": {"panel": dict(Counter(r["commute"] for r in rows if "commute" in r).most_common())},
            "smoking": {"panel": share("smoking"),
                        "panel_male": share("smoking", subset=lambda p, r: p["sex"] == "남자"),
                        "panel_female": share("smoking", subset=lambda p, r: p["sex"] == "여자")},
            "health_good_not_shown": {"panel": share("health_good")},
            "hypertension_30plus": {"panel": share("hypertension", subset=lambda p, r: p["age"] >= 30)},
            "diabetes_30plus": {"panel": share("diabetes", subset=lambda p, r: p["age"] >= 30)},
            "employment": {"panel": dict(Counter(r["employment"] for r in rows if "employment" in r))},
            "nps_65plus": {"panel": share("nps", subset=lambda p, r: p["age"] >= 65),
                           "official_65plus_2024": 0.521},
            "networth_quintile": {"panel": dict(sorted(Counter(r["networth"] for r in rows if "networth" in r).items())),
                                  "official": "각 20%(가구 기준)"},
            "nonregular_of_wage": {"panel": share("nonregular"), "official_2026_08": "38%(임금근로자 중)"},
            "dual_earner_of_married": {"panel": share("dual_earner"), "official_2025": 0.486},
            "elder_function_65plus": {"panel": dict(Counter(r["function"] for r in rows if "function" in r)),
                                      "official_2023": {"none": 0.814, "iadl": 0.098, "adl": 0.087}},
            "elder_care_of_limited": {"panel": share("care"), "official_2023": 0.472},
            "digital": {"panel_by_age": {g: dict(Counter(r["digital"] for r in rows if "digital" in r and lo <= by_uuid[r["uuid"]]["age"] < hi))
                                         for g, lo, hi in (("19-59", 0, 60), ("60-69", 60, 70), ("70+", 70, 200))}},
            "basic_pension_65plus": {"panel": share("basic_pension", subset=lambda p, r: p["age"] >= 65),
                                     "official_65plus_2024": 0.676},
            **{f"{k}_kchs": {"panel": share(k), "kchs_district_mean": round(
                sum(v["rate"] for v in t[k]["by_district"].values()) / len(t[k]["by_district"]), 4)}
               for k in ("drinking", "obesity", "walking", "stress", "depression")},
            "reading": {"panel": share("reading"), "official_2025": t["reading"]["전체"]},
            "arts": {"panel": share("arts"), "official_2025": t["arts"]["전체"]},
            "pet": {"panel_people": share("pet"), "official_households_2025": t["pet"]["전체"]},
            "employment_insurance_of_wage": {"panel": share("employment_insurance"), "official_2026_08": 0.77},
            # survey-table traits: panel share among the eligible vs the table's published total (the private
            # insurance total also counts children, who are insured more often than adults)
            **{attr: {"panel": share(attr), "official": t[spec["table"]]["전체"]}
               for attr, spec in life_context.SURVEY_ATTRS.items()},
        },
        "held_out": held_out(rows, by_uuid, t),
        "arts_by_work_and_disability": arts_held_out(rows, by_uuid, t),
        "used_as_targets": {"mean_income_by_province": {"rows": reg_rows,
                                                        "pearson": round(pearson([x[1] for x in reg_rows],
                                                                                 [x[2] for x in reg_rows]), 3)},
                            "mean_income_by_tenure": {"rows": ten_rows}},
    }
    (OUT / "addons-v2.json").write_text(json.dumps(catalog(rows, by_uuid), ensure_ascii=False, indent=1) + "\n",
                                         encoding="utf-8")
    (OUT / "report-v2.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
