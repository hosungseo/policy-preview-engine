"""Cross-branch contracts, using only synthetic data and injected or mock models."""
import json
import sqlite3
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from pp import __main__ as cli
from pp import attribution, budget, diagnostics, persona_contrast, pipeline, provenance, scenario
from ppservice.survey import aggregate, lint, visit
from test_attribution_labels import OPTIONS, SPEC, _answers, _people
from test_e2e import POLICY
from test_rerun_budget import synthetic_service

ENGINE = Path(__file__).resolve().parents[1]


def test_selection_card_and_fingerprint_share_actual_inputs(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setenv("PP_RUNS_DIR", str(tmp_path / "runs"))
    with sqlite3.connect(persona_db) as conn:
        for row_id, in conn.execute("SELECT id FROM persona").fetchall():
            conn.execute("UPDATE persona SET uuid=? WHERE id=?", (str(uuid5(NAMESPACE_URL, f"synthetic:{row_id}")), row_id))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(POLICY), encoding="utf-8")
    job = pipeline.Run(policy_path, n_rep=12, n_aff=4)
    job.run(only=("segment", "panel"))
    receipt = json.loads(job.path("selection.json").read_text())
    people = json.loads(job.path("personas.json").read_text())
    assert receipt["uuids"] == [p["uuid"] for p in people]
    assert job.meta["personas_hash"] == provenance.input_hash(people)
    card = json.loads((ENGINE / "scenarios/examples/offline-help-v1.json").read_text())
    card["persona_uuid"] = receipt["uuids"][0]
    card["observed_fields"] = {"age": people[0]["age"]}
    assert scenario.validate_scenario(card)["status"] == "deferred"
    policy_path.write_text(json.dumps({**POLICY, "text": POLICY["text"] + "수정 문안"}), encoding="utf-8")
    with pytest.raises(provenance.InputMismatch):
        pipeline.Run(policy_path, n_rep=12, n_aff=4)
    assert json.loads(job.path("policy.json").read_text()) == POLICY
    assert json.loads(job.path("selection.json").read_text()) == receipt


def test_income_card_retains_both_cautions_and_source():
    people = _people(600, "배우자와 거주", 1)
    poor = {p["uuid"] for i, p in enumerate(people) if i % 3 == 0}
    context = {p["uuid"]: {"income": "lt10" if p["uuid"] in poor else "ge100"} for p in people}
    answers = _answers(people, lambda p: p["uuid"] in poor)
    result = visit.view(SPEC, people, answers, OPTIONS, "synthetic+addons-finance-0123abcd",
                        everyone=people, context=context, roster={})
    card = next(c for c in result["cards"] if c["attribute"] == "income")
    for caution in (aggregate.MONEY_LIMIT, diagnostics.EDU_INCOME_CARD_CAUTION):
        assert caution in card["caution"] and caution in result["copy_text"]
    assert attribution.validate(result["attribution"]) == []
    assert result["diagnostics"]["n"] == 600
    assert result["warnings"]


def test_question_keeps_proxy_and_reliability_warnings():
    question = "앱으로 직접 신청하실 수 있습니까? 지원금을 매달 얼마나 받으실지 불안하십니까?"
    codes = {f["code"] for f in lint.check("", question, ["매우 그렇다", "그렇다", "아니다", "전혀 아니다"])}
    assert {"amount_calc", "procedure_ability", "reliability_many_options", "reliability_subjective_topic"} <= codes


def test_service_result_keeps_budget_identity_source_and_diagnostics(synthetic_service):
    settings, db, people, uid, sid, run, runner = synthetic_service
    runner.run_one(*runner._claim())
    row = db.one("SELECT status, result FROM runs WHERE id=?", (run["id"],))
    assert row["status"] == "succeeded"
    result = json.loads(row["result"])
    assert len(result["input_hash"]) == 64 and result["budget"]["calls"] == 12
    assert attribution.validate(result["attribution"]) == []
    assert result["diagnostics"]["n"] == len(people)


def test_persona_contrast_shares_persistent_call_limit_across_arms(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = persona_contrast.make_demo_synthetic_people(20)
    spec = {**SPEC, "options": OPTIONS}
    ledger = tmp_path / "contrast.budget.json"
    with pytest.raises(budget.BudgetExceeded):
        persona_contrast.run_contrast(spec, people, limits=budget.Limits(max_calls=3), budget_path=ledger)
    assert json.loads(ledger.read_text())["calls"] == 3
    with pytest.raises(budget.BudgetExceeded):
        persona_contrast.run_contrast(spec, people, limits=budget.Limits(max_calls=3), budget_path=ledger)
    assert json.loads(ledger.read_text())["calls"] == 3


def test_legacy_partial_service_answers_still_fail_closed(synthetic_service):
    from ppservice import jobs

    settings, db, people, uid, sid, run, runner = synthetic_service
    run_id, attempt = runner._claim()
    partial = jobs.Runner(db, settings, run_id, attempt, uid, runner.stop)
    partial.save_answer("main", people[0]["uuid"], [0.5, 0.25, 0.25], 900)
    runner.run_one(run_id, attempt)
    row = db.one("SELECT status, error_code FROM runs WHERE id=?", (run_id,))
    assert row["status"] == "failed" and row["error_code"] == "input_changed"
    assert runner.evaluate.calls == 0
