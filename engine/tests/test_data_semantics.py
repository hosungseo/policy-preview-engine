"""Missing cells, household units, source identity and panel denominators, without model or network calls."""
import copy
import gzip
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

from pp import analyze_llm, life_context as lc, pipeline, provenance
from ppservice.survey import visit
from test_analyze_llm import people_for, rx
from test_life_context import person


def script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_household_income_venue_labels():
    labels = [label for label, _ in visit.ADDON_GROUPS["income"][1].values()]
    assert all("가구 연소득" in label and "개인" not in label for label in labels)


def test_missing_and_zero_rates_are_different(monkeypatch):
    table = copy.deepcopy(lc.tables())
    p = person(1, age=65)
    table["livelihood"]["서울"]["남자"].pop("65", None)
    table["disability"]["rate"][p["district"]]["남자"].pop("65", None)
    table["nps_oldage"]["서울"]["남자"].pop("65", None)
    monkeypatch.setattr(lc, "tables", lambda: table)
    assigned, diag = lc.build([p])
    for key in ("livelihood", "disability", "nps"):
        assert assigned[p["uuid"]][key] is None
        assert assigned[p["uuid"]]["value_status"][key] == "unknown"
    assert diag["finance_unit"] == "household_to_person_approximation"
    assert diag["limitations"] == [lc.FINANCE_LIMIT, lc.BENEFIT_ASSET_LIMIT]
    table["livelihood"]["서울"]["남자"]["65"] = 0
    table["disability"]["rate"][p["district"]]["남자"]["65"] = 0
    table["nps_oldage"]["서울"]["남자"]["65"] = 0
    assigned, _ = lc.build([p])
    assert all(assigned[p["uuid"]][key] is False for key in ("livelihood", "disability", "nps"))


def test_unknown_commute_and_inapplicable_commute(monkeypatch):
    monkeypatch.setattr(lc, "commute_probs", lambda p: None)
    assigned, _ = lc.build([person(1), person(2, occupation="무직")])
    assert assigned["u-1"]["commute"] is assigned["u-2"]["commute"] is None
    assert assigned["u-1"]["value_status"]["commute"] == "unknown"
    assert assigned["u-2"]["value_status"]["commute"] == "not_applicable"
    assert "출퇴근" not in lc.block(assigned["u-1"])


def test_unpublished_finance_bands_are_not_zero_targets(monkeypatch):
    compiler = script("build_persona_context")
    rows = [{"C1_NM": "전체", "C2_NM": "1000만원 미만", "DT": "0"}]
    monkeypatch.setattr(compiler, "raw", lambda name: rows if name == "income_band" else [])
    row = compiler.finance()["income_band"]["전체"]
    assert row["lt10"] == 0 and row["ge100"] is None
    probs, _ = lc.rake(1, {"lo": 0.5, "hi": 0.5}, [([0], {"lo": None, "hi": 0.9})])
    assert probs == [{"lo": 0.5, "hi": 0.5}]
    table = copy.deepcopy(lc.tables())
    table["finance"]["income_band"]["전체"] = row
    monkeypatch.setattr(lc, "tables", lambda: table)
    with pytest.raises(ValueError, match="incomplete"):
        lc.build([person(1)])


def test_unknown_sums_and_income_mobility(monkeypatch):
    compiler = script("build_persona_context")
    assert compiler.known_sum([0, 0]) == 0
    assert compiler.known_sum([1, None]) is None and compiler.known_sum([]) is None
    rows = [{"C1_NM": "남자", "C2_NM": "19~39세", "C3_NM": "1분위", "DT": "-", "ITM_ID": "T10", "PRD_DE": "2024"},
            {"C1_NM": "남자", "C2_NM": "19~39세", "C3_NM": "1분위", "DT": "0", "ITM_ID": "T11", "PRD_DE": "2024"}]
    monkeypatch.setattr(compiler, "raw", lambda name: rows if name == "mobility_joint" else [])
    cell = compiler.income_mobility()["by_year"]["2024"]["남자"]["19~39세"]
    assert cell["prior"][0] is None and cell["joint"][0][0] == 0
    assert cell["joint"][0][1] is None and cell["current"][0] is None


def test_download_uses_resolved_revision(monkeypatch, tmp_path):
    builder = script("build_panel_from_nemotron")
    calls = []
    fake = types.ModuleType("huggingface_hub")
    fake.HfApi = lambda: types.SimpleNamespace(dataset_info=lambda repo, revision: types.SimpleNamespace(sha="a" * 40))
    fake.snapshot_download = lambda **kw: calls.append(kw) or str(tmp_path)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)
    monkeypatch.setattr(builder, "parquet_files", lambda path: [])
    monkeypatch.setattr(builder, "choose", lambda *args: set())
    monkeypatch.setattr(builder, "write_bundle", lambda *args: {"panel_version": "test"})
    out = tmp_path / "panel.gz"
    builder.main(["--out", str(out), "--revision", "release"])
    assert calls[0]["revision"] == "a" * 40
    assert json.loads(provenance.metadata_path(out).read_text())["source_revision"] == "a" * 40


def test_pipeline_records_artifact_and_revision(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_PERSONA_SOURCE", "db")
    provenance.write_metadata(persona_db, {"source_repo": "test", "source_revision": "b" * 40, "revision_status": "resolved"})
    policy = tmp_path / "policy.json"
    policy.write_text(json.dumps({"id": "meta", "title": "t", "kind": "test", "text": "policy"}))
    run = pipeline.Run(policy, run_dir=tmp_path / "run")
    assert run.meta["panel_version"] and run.meta["source_revision"] == "b" * 40
    bundle = tmp_path / "legacy.gz"
    bundle.write_bytes(gzip.compress(b'{}\n'))
    assert provenance.artifact(bundle, compressed=True)["source_revision"] is None


def test_issue_denominators_never_mix_panels():
    rows = [rx(i, support=i - 2) for i in range(1, 5)]
    people = people_for(rows)
    for i, p in enumerate(people.values()):
        p["panel"] = "rep" if i < 3 else "aff"
    [issue] = analyze_llm.enrich_issues([{"title": "test", "member_ids": ["r1", "r4"]}], rows, people)
    assert issue["n"] == 1 and issue["share"] == 0.333 and issue["mean"] == -1
    assert issue["by_panel"]["aff"]["n"] == 1 and issue["by_panel"]["aff"]["share"] == 1
    assert issue["by_panel"]["aff"]["caution"] == "전체 비율로 읽지 않음"
