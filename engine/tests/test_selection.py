import json

import pytest

from pp import llm, pipeline, provenance


def make_run(tmp_path, monkeypatch, **kwargs):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    policy = tmp_path / "policy-input.json"
    policy.write_text(json.dumps({"id": "selection-test", "title": "시험", "kind": "가상 정책안",
                                  "text": "고령자 도시철도 무임승차 연령 시험입니다."}, ensure_ascii=False))
    return pipeline.Run(policy, run_dir=tmp_path / "run", n_rep=20, n_aff=8, seed=7, **kwargs)


def test_selection_receipt_records_actual_conditions_uuids_counts_and_revision(persona_db, tmp_path, monkeypatch):
    provenance.write_metadata(persona_db, {"source_repo": "invented-fixture", "source_revision": "b" * 40,
                                           "revision_status": "user_supplied"})
    job = make_run(tmp_path, monkeypatch)
    original = llm.complete_json
    raw = {"filters": [{"age_min": 65, "province_in": ["경북", "전라북도"]}],
           "keywords": ["지하철로", "택시"], "semantic_query": "", "rationale": "가상 시험"}

    def complete(task, *args, **kwargs):
        return kwargs["validate"](raw) if task == "target" else original(task, *args, **kwargs)

    monkeypatch.setattr(llm, "complete_json", complete)
    job.stage_panel()
    audit = json.loads(job.path("selection.json").read_text())
    people = json.loads(job.path("personas.json").read_text())
    assert audit["data"]["source_revision"] == "b" * 40
    assert audit["data"]["panel_version"] == provenance.artifact(persona_db)["panel_version"]
    assert audit["requested_spec"] == raw
    assert audit["normalized_spec"]["filters"][0]["province_in"] == ["경상북", "전북"]
    assert audit["uuids"] == [p["uuid"] for p in people]
    assert audit["selected_count"] == len(people) == len(set(audit["uuids"]))
    for key, name in (("representative", "rep"), ("affected", "aff")):
        group = audit[key]
        assert group["uuids"] == [p["uuid"] for p in people if p["panel"] == name]
        assert group["selected_count"] == len(group["uuids"])
    rep = audit["representative"]
    assert rep["eligible_count"] == 170 and rep["selected_count"] == 20 and rep["seed"] == 7
    assert sum(s["seats"] for s in rep["strata"]) == rep["selected_count"]
    aff = audit["affected"]
    assert aff["status"] == "candidate_not_eligibility"
    sql = aff["filter_groups"][0]
    assert sql["parameters"]["province"] == '["경상북", "전북"]'
    assert sql["parameters"]["age_min"] == 65 and sql["order"] == "id ASC" and sql["sampling"] == "none"
    assert aff["fts"]["requested_keywords"] == ["지하철로", "택시"]
    assert aff["fts"]["usable_keywords"] == ["지하철로", "택시"]
    job.stage_panel()
    assert json.loads(job.path("selection.json").read_text()) == audit


def test_pool_missing_uuid_fails_before_target_model_call(persona_db, tmp_path, monkeypatch):
    job = make_run(tmp_path, monkeypatch, pool_uuids=["u00001", "missing"])

    def unexpected(*args, **kwargs):
        pytest.fail("missing pool UUID must be detected before calling any model")

    monkeypatch.setattr(llm, "complete_json", unexpected)
    with pytest.raises(ValueError, match="missing"):
        job.stage_panel()
    assert not job.path("selection.json").exists()


def test_unknown_data_revision_is_preserved(persona_db, tmp_path, monkeypatch):
    job = make_run(tmp_path, monkeypatch)
    job.stage_panel()
    data = json.loads(job.path("selection.json").read_text())["data"]
    assert data["source_revision"] is None and data["revision_status"] == "unknown"
