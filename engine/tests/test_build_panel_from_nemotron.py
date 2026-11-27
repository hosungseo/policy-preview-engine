"""scripts/build_panel_from_nemotron.py on a tiny synthetic parquet with the dataset's columns (no download)."""
import gzip
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

pa = pytest.importorskip("pyarrow")
pq = pytest.importorskip("pyarrow.parquet")

from pp import bundle_db, config  # noqa: E402
from pp.panel import allocate  # noqa: E402

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_panel_from_nemotron.py"
PROVINCES = ["서울", "경기", "부산", "전라남", "제주"]


def _script():
    spec = importlib.util.spec_from_file_location("build_panel_from_nemotron", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_rows(n: int) -> list[dict]:
    """Made-up people with the column names of nvidia/Nemotron-Personas-Korea; none of the text is from the dataset."""
    rows = []
    for i in range(n):
        prov = PROVINCES[i % len(PROVINCES)]
        name = f"합성{i:03d}"
        rows.append({
            "uuid": f"{i:032x}", "persona": f"{name} 씨는 {prov}에 사는 합성 인물입니다.\n둘째 줄",
            "professional_persona": f"{name} 씨는 일을 합니다.", "sports_persona": "", "arts_persona": "",
            "travel_persona": "", "culinary_persona": "", "family_persona": f"{name} 씨는 가족과 지냅니다.",
            "cultural_background": f"{prov}에서 자랐습니다.", "skills_and_expertise": "", "skills_and_expertise_list": "[]",
            "hobbies_and_interests": "", "hobbies_and_interests_list": "[]", "career_goals_and_ambitions": "",
            "sex": "여자" if i % 2 else "남자", "age": 17 + (i * 7) % 70, "marital_status": "미혼",
            "military_status": "비현역", "family_type": "혼자 거주", "housing_type": "아파트",
            "education_level": "고등학교", "bachelors_field": "해당없음", "occupation": "사무 보조원",
            "district": f"{prov}-중구", "province": prov, "country": "대한민국",
        })
    return rows


@pytest.fixture
def parquet_dir(tmp_path):
    folder = tmp_path / "parquet"
    folder.mkdir()
    rows = _synthetic_rows(400)
    for part in range(2):
        pq.write_table(pa.Table.from_pylist(rows[part::2]), folder / f"train-{part:05d}-of-00002.parquet")
    return folder


def test_bundle_keeps_strata_and_parses(parquet_dir, tmp_path):
    out = tmp_path / "panel.jsonl.gz"
    assert _script().main(["--parquet-dir", str(parquet_dir), "--n", "100", "--out", str(out)]) == 0
    lines = gzip.decompress(out.read_bytes()).decode("utf-8").splitlines()
    rows = [json.loads(x) for x in lines]
    metadata = json.loads(out.with_name(out.name + ".meta.json").read_text())
    assert metadata["source_revision"] is None and metadata["revision_status"] == "unknown"
    import hashlib
    assert metadata["panel_version"] == hashlib.sha256(gzip.decompress(out.read_bytes())).hexdigest()[:12]
    assert len(rows) == 100 and all(r["age"] >= 19 for r in rows)
    adults = [r for r in _synthetic_rows(400) if r["age"] >= 19]
    sizes = Counter((r["province"], config.age_band(r["age"]), r["sex"]) for r in adults)
    seats = {k: v for k, v in allocate(dict(sizes), 100).items() if v}
    assert Counter((r["province"], r["age_band"], r["sex"]) for r in rows) == seats  # proportional seats per stratum
    assert {r["capital"] for r in rows if r["province"] in ("서울", "경기")} == {True}
    parsed = [bundle_db.parse_profile(r) for r in rows]  # the deep pipeline reads the profile text back
    assert parsed[0]["district"].endswith("-중구") and "\n" not in parsed[0]["persona"]
    again = tmp_path / "again.jsonl.gz"
    _script().main(["--parquet-dir", str(parquet_dir), "--n", "100", "--out", str(again)])
    assert gzip.decompress(again.read_bytes()) == gzip.decompress(out.read_bytes())  # same seed, same panel


def test_persona_db_has_the_engine_schema(parquet_dir, tmp_path):
    db = tmp_path / "persona.db"
    _script().main(["--parquet-dir", str(parquet_dir), "--n", "50", "--out", str(tmp_path / "p.jsonl.gz"),
                    "--persona-db", str(db), "--revision", "a" * 40])
    metadata = json.loads(db.with_name(db.name + ".meta.json").read_text())
    assert metadata["source_revision"] == "a" * 40 and metadata["revision_status"] == "user_supplied"
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT count(*) FROM persona").fetchone()[0] == 400
    hit = conn.execute("SELECT count(*) FROM persona_fts WHERE persona_fts MATCH '가족과'").fetchone()[0]
    assert hit == 400
    cols = [r[1] for r in conn.execute("PRAGMA table_info(persona)")]
    assert cols[:3] == ["id", "uuid", "persona"] and cols[-2:] == ["district", "province"]
