"""Count, per district, how many of the 1,000,000 synthetic people fall in each base group of the visit view.

The 20,000-person panel answers the question; this table says where such people live with far more people per
district (about 4,000 instead of about 80). Only attributes that are plain columns in the full table are counted.
  python scripts/build_roster_1m.py   # reads the persona DB (PP_PERSONA_DB), writes ppservice/data/roster-1m.json.gz
"""
import gzip
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import config
from ppservice.survey import visit

OUT = Path(__file__).resolve().parents[1] / "ppservice" / "data" / "roster-1m.json.gz"
SKIP = {"권역", "시도"}  # places themselves


def band(age: int) -> str:
    return "19–29세" if age < 30 else "70세 이상" if age >= 70 else f"{age // 10 * 10}대"


def main() -> None:
    db = sqlite3.connect(f"file:{config.persona_db()}?mode=ro", uri=True)
    districts: Counter = Counter()
    groups: dict[str, Counter] = defaultdict(Counter)
    rows = db.execute("select province, district, age, sex, education_level, marital_status, family_type, housing_type,"
                      " occupation from persona")
    for province, district, age, sex, edu, marital, family, housing, job in rows:
        p = {"age_band": band(age), "sex": sex, "province": province, "capital": False, "profile": ""}
        h = {"학력": edu, "혼인": marital, "가구": family, "주거": housing, "직업": job}
        name = f"{visit.PROVINCE.get(province, province)} {district.partition('-')[2]}".strip()
        districts[name] += 1
        for attr, label, _ in visit._base_groups(p, h):
            if attr not in SKIP:
                groups[label][name] += 1
    out = {"n": sum(districts.values()), "districts": dict(districts), "groups": {k: dict(v) for k, v in groups.items()}}
    OUT.write_bytes(gzip.compress(json.dumps(out, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), mtime=0))
    print(out["n"], len(districts), {k: sum(v.values()) for k, v in groups.items()}, OUT.stat().st_size)


if __name__ == "__main__":
    main()
