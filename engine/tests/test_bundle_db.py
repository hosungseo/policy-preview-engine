"""The 20k panel bundle as a persona source for the deep pipeline."""
import gzip
import json
import sqlite3

import pytest

from pp import bundle_db, config, panel, personas, pipeline, prompts
from tests.conftest import make_rows


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    rows = make_rows(170)
    for i, r in enumerate(rows):
        r["name"] = personas.extract_name(r["persona"]) if i % 5 else ""
        if not r["name"]:
            r["persona"] = "이름 없이 시작하는 서술입니다."
        if i % 7 == 0:
            r["district"] = "경기-성남시 (분당구)"  # brackets inside a field must survive the round trip
    lines = [json.dumps({"uuid": r["uuid"], "sex": r["sex"], "age": r["age"], "age_band": config.age_band(r["age"]),
                         "province": r["province"], "capital": r["province"] in ("서울", "경기", "인천"),
                         "profile": prompts.persona_profile(r)}, ensure_ascii=False) for r in rows]
    path = tmp_path / "panel.jsonl.gz"
    path.write_bytes(gzip.compress("\n".join(lines).encode("utf-8")))
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(path))
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PP_PERSONA_SOURCE", "bundle")
    return rows


def test_profile_round_trip(bundle):
    conn = personas.connect()
    assert conn.execute("SELECT COUNT(*) FROM persona").fetchone()[0] == 170
    by_uuid = {r["uuid"]: r for r in bundle}
    people = personas.fetch(conn, [r[0] for r in conn.execute("SELECT id FROM persona")])
    for p in people:
        want = by_uuid[p["uuid"]]
        for key in ("sex", "age", "marital_status", "family_type", "housing_type", "education_level", "occupation",
                    "district", "province", "professional_persona", "family_persona", "cultural_background"):
            assert p[key] == want[key], key
        assert p["name"] == want["name"]
        assert prompts.persona_profile(p) == prompts.persona_profile(want)


def test_persona_queries_on_bundle(bundle):
    conn = personas.connect()
    assert personas.fts_ids(conn, ["지하철로"])
    assert personas.filter_ids(conn, {"occupation_like": ["간호사"]})
    assert "간호사" in personas.occupation_names(conn)
    assert personas.population(conn)["total"] == 170
    uuids = [r["uuid"] for r in bundle[:5]]
    assert len(personas.ids_for_uuids(conn, uuids)) == 5
    assert len(panel.sample_representative(personas.PersonaIndex.load(conn).strata(), 30)) == 30


def test_cache_is_reused_and_read_only(bundle):
    first = bundle_db.ensure()
    stamp = first.stat().st_mtime_ns
    assert bundle_db.ensure() == first and first.stat().st_mtime_ns == stamp
    with pytest.raises(sqlite3.OperationalError):
        personas.connect().execute("DELETE FROM persona")


def test_source_switch(persona_db, monkeypatch):
    assert personas.source() == "db"
    monkeypatch.setenv("PP_PERSONA_SOURCE", "bundle")
    assert personas.source() == "bundle"
    monkeypatch.delenv("PP_PERSONA_SOURCE")
    monkeypatch.setenv("PP_PERSONA_DB", str(persona_db.parent / "missing.db"))
    assert personas.source() == "bundle"


@pytest.mark.needs_panel
def test_real_bundle_parses():
    raw = gzip.decompress(bundle_db.BUNDLE.read_bytes()).decode("utf-8").splitlines()
    rows = [bundle_db.parse_profile(json.loads(line)) for line in raw if line.strip()]
    assert len(rows) == 20000
    assert all(r["occupation"] and r["district"] and r["province"] in config.REGION_OF for r in rows)
    assert all(r["education_level"] and r["marital_status"] and r["family_type"] and r["housing_type"] for r in rows)


def test_pipeline_pool_and_run_dir(bundle, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    policy = tmp_path / "p.json"
    policy.write_text(json.dumps({"id": "pool", "title": "시험 정책", "kind": "가상 정책안",
                                  "text": "1. 주요 내용\n가. 무임승차 기준 연령을 70세로 올린다.\n"}, ensure_ascii=False),
                      encoding="utf-8")
    pool = [r["uuid"] for r in bundle[:90]]
    seen = []
    job = pipeline.Run(policy, n_rep=20, n_aff=5, n_jev=40, n_alt=10, workers=2, allow_mock=True,
                       run_dir=tmp_path / "work", pool_uuids=pool, on_stage=seen.append)
    job.run(only=("segment", "clarity", "panel", "react", "issues", "jev"))
    assert seen == ["segment", "clarity", "panel", "react", "issues", "jev"]
    people = json.loads((tmp_path / "work" / "personas.json").read_text(encoding="utf-8"))
    assert sum(p["panel"] == "rep" for p in people) == 20
    assert all(p["uuid"] in pool for p in people if p["panel"] == "rep")
    quant = json.loads((tmp_path / "work" / "jev_quant.json").read_text(encoding="utf-8"))
    assert len(quant) == 40 and all(q["uuid"] in pool for q in quant)
    meta = json.loads((tmp_path / "work" / "meta.json").read_text(encoding="utf-8"))
    assert any("의미 검색 경로 생략" in f for f in meta["fallbacks"])


def test_fixed_statements_match_columns(tmp_path):
    conn = sqlite3.connect(tmp_path / "x.db")
    conn.execute(bundle_db.CREATE_SQL)
    assert tuple(r[1] for r in conn.execute("PRAGMA table_info(persona)")) == bundle_db.COLUMNS
    assert bundle_db.INSERT_SQL.count("?") == len(bundle_db.COLUMNS)
    assert all(c in bundle_db.FTS_SQL and c in bundle_db.FTS_FILL_SQL for c in bundle_db.FTS_COLS)

