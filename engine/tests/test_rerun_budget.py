import json
import threading
import time

import pytest

from pp import budget, config, jev, llm, pipeline, prompts, provenance, react
from pp.compare import compare_runs


POLICY = {"id": "safe", "title": "시험 문안", "kind": "가상", "text": "만 70세 이상은 요금을 지원합니다."}


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.mark.parametrize("change", ["text", "question", "model", "prompt", "data", "people", "seed"])
def test_input_changes_refused_before_overwrite(persona_db, tmp_path, monkeypatch, change):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    policy = write(tmp_path / "policy.json", POLICY)
    directory = tmp_path / "run"
    job = pipeline.Run(policy, run_dir=directory)
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    kwargs = {}
    if change in ("text", "question"):
        write(policy, {**POLICY, change: "바뀐 입력"})
    elif change == "model":
        monkeypatch.setattr(config, "REACT_MODEL", "another-model")
    elif change == "prompt":
        monkeypatch.setattr(prompts, "REACT_SYSTEM", "new-prompt-version")
    elif change == "data":
        kwargs["data_meta"] = {"panel_version": "another-data-version"}
    elif change == "people":
        kwargs["pool_uuids"] = ["u00001"]
    elif change == "seed":
        kwargs["seed"] = 99
    with pytest.raises(provenance.InputMismatch):
        pipeline.Run(policy, run_dir=directory, **kwargs)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before
    assert len(job.meta["input_hash"]) == 64


def test_same_inputs_resume_and_legacy_refused(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    policy = write(tmp_path / "policy.json", POLICY)
    folder = tmp_path / "run"
    first = pipeline.Run(policy, run_dir=folder)
    assert pipeline.Run(policy, run_dir=folder).meta["input_hash"] == first.meta["input_hash"]
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    write(legacy / "segments.json", [])
    with pytest.raises(provenance.InputMismatch):
        pipeline.Run(policy, run_dir=legacy)


def test_saved_persona_profile_change_is_refused(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    policy = write(tmp_path / "policy.json", POLICY)
    job = pipeline.Run(policy, run_dir=tmp_path / "run", n_rep=3, n_aff=0)
    job.run(only=("segment", "panel"))
    people = json.loads(job.path("personas.json").read_text())
    people[0]["persona"] = "수정된 인물"
    write(job.path("personas.json"), people)
    with pytest.raises(provenance.InputMismatch):
        pipeline.Run(policy, run_dir=job.dir, n_rep=3, n_aff=0)


def test_reaction_profile_or_prompt_change_cannot_resume(tmp_path, monkeypatch):
    from conftest import make_rows
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    people = make_rows(2)
    out = tmp_path / "react.jsonl"
    rows, _ = react.run_reactions(people, POLICY["text"], out)
    assert all(len(row["input_hash"]) == 64 for row in rows)
    before = out.read_bytes()
    people[0]["persona"] = "수정된 인물 설명"
    with pytest.raises(provenance.InputMismatch):
        react.run_reactions(people, POLICY["text"], out)
    assert out.read_bytes() == before


def test_shared_parallel_call_and_concurrency_limits(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    ledger = budget.Budget(budget.Limits(max_calls=7, max_concurrency=2))
    lock = threading.Lock()
    observed = {"active": 0, "peak": 0, "calls": 0}
    def one():
        try:
            with budget.attempt("llm:test", "input", mock=True):
                with lock:
                    observed["active"] += 1
                    observed["calls"] += 1
                    observed["peak"] = max(observed["peak"], observed["active"])
                time.sleep(.005)
                with lock:
                    observed["active"] -= 1
        except budget.BudgetExceeded:
            pass
    with ledger.scope(), budget.ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: one(), range(20)))
    assert observed["calls"] == ledger.snapshot()["calls"] == 7
    assert observed["peak"] == 2


def test_invalid_json_retry_accounted_and_terminal_limit(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PP_LLM_INPUT_USD_PER_M", "1")
    monkeypatch.setenv("PP_LLM_OUTPUT_USD_PER_M", "2")
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)
    calls = []
    def fake(*args):
        calls.append(1)
        budget.record_usage({"prompt_tokens": 100, "completion_tokens": 30})
        return "bad JSON" if len(calls) == 1 else "{}"
    monkeypatch.setattr(llm, "_call", fake)
    ledger = budget.Budget(budget.Limits(max_calls=2))
    with ledger.scope():
        assert llm.complete_json("react", "system", "prompt", model="model") == {}
        with pytest.raises(budget.BudgetExceeded):
            llm.complete_json("summary", "system", "prompt", model="model", retries=10)
    assert len(calls) == 2
    assert ledger.snapshot()["cost_usd"] == pytest.approx(.00032)
    assert ledger.snapshot()["cost_status"] == "known"


def test_unknown_usage_preserves_reservation_after_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_INPUT_USD_PER_M", "1")
    monkeypatch.setenv("PP_LLM_OUTPUT_USD_PER_M", "1")
    limits = budget.Limits(max_calls=2, max_output_tokens=10, max_cost_usd=.002)
    path = tmp_path / "budget.json"
    first = budget.Budget(limits, path)
    with first.scope(), first.attempt("llm:react", "input"):
        pass  # timeout or response without usage
    old_cost = first.snapshot()["cost_usd"]
    second = budget.Budget(limits, path)
    with second.scope():
        with pytest.raises(budget.BudgetExceeded):
            with second.attempt("llm:summary", "input"):
                pytest.fail("must not dispatch")
    assert second.snapshot()["cost_usd"] == old_cost > 0
    assert second.snapshot()["calls"] == 1
    assert second.snapshot()["cost_status"] == "unknown"


def test_unpriced_and_cli_are_not_reported_free(monkeypatch):
    for name in ("PP_LLM_INPUT_USD_PER_M", "PP_LLM_OUTPUT_USD_PER_M"):
        monkeypatch.delenv(name, raising=False)
    with budget.Budget().scope():
        with pytest.raises(budget.BudgetExceeded):
            with budget.attempt("llm:summary", "input"):
                pytest.fail("must not call unpriced model")
    with budget.Budget(budget.Limits(max_cost_usd=None)).scope() as ledger:
        with budget.attempt("llm:summary", "input", cli=True):
            pass
    assert ledger.snapshot()["cost_status"] == "unknown"


def test_jev_failed_paid_response_is_charged(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake")
    monkeypatch.setattr(jev._limiter, "wait", lambda: None)
    monkeypatch.setattr(jev.time, "sleep", lambda _: None)
    calls = []
    def fake(*args, **kwargs):
        calls.append(1)
        return json.dumps({"answers": {} if len(calls) == 1 else {"q": {}}, "usage": {"input_tokens": 100}}).encode()
    monkeypatch.setattr(jev.net, "post", fake)
    with budget.Budget().scope() as ledger:
        jev.evaluate("input", {"q": {"type": "noul"}}, cache=False)
    assert ledger.snapshot()["calls"] == 2
    assert ledger.snapshot()["cost_usd"] == pytest.approx(.0000084)


def test_comparison_preserves_uuid_question_and_records_drift(tmp_path, monkeypatch):
    from conftest import make_rows
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    parent = tmp_path / "parent"
    parent.mkdir()
    people = make_rows(3)
    write(parent / "policy.json", POLICY)
    write(parent / "personas.json", people)
    write(parent / "meta.json", {"panel_version": "frozen-v1", "input_hash": "parent-hash"})
    revised = write(tmp_path / "revision.json", {**POLICY, "text": "지원 연령을 만 65세로 낮춥니다."})
    calls = []
    def fake(task, system, prompt, **kwargs):
        calls.append(prompt)
        return {"support": 1 if len(calls) % 2 else -1, "reason": "충분한 시험용 이유", "impact": "직접"}
    monkeypatch.setattr(llm, "complete_json", fake)
    result_path = compare_runs(parent, revised, tmp_path / "compare", question="지원안에 찬성하십니까?", workers=1)
    result = json.loads(result_path.read_text())
    assert len(calls) == 18
    assert all("지원안에 찬성하십니까?" in prompt for prompt in calls)
    assert [r["uuid"] for r in result["paired"]] == [p["uuid"] for p in people]
    assert result["before"]["repeat_drift_pp"] > 0
    assert all(row["before_range"] == 2 for row in result["paired"])
    compare_runs(parent, revised, tmp_path / "compare", question="지원안에 찬성하십니까?", workers=1)
    assert len(calls) == 18  # identical interrupted/repeated command reuses only identical inputs
    with pytest.raises(provenance.InputMismatch):
        compare_runs(parent, revised, tmp_path / "compare", question="다른 질문?", workers=1)


def test_http_output_limit_sent_and_usage_captured(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PP_LLM_MODEL", "fake-model")
    monkeypatch.setenv("PP_LLM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("PP_LLM_INPUT_USD_PER_M", "0")
    monkeypatch.setenv("PP_LLM_OUTPUT_USD_PER_M", "0")
    bodies = []
    def fake(url, body, **kwargs):
        bodies.append(json.loads(body))
        return json.dumps({"choices": [{"message": {"content": "{}"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 1}}).encode()
    monkeypatch.setattr(llm.net, "post", fake)
    with budget.Budget(budget.Limits(max_output_tokens=23)).scope() as ledger:
        llm.complete_json("summary", "system", "input", model=config.SYNTH_MODEL)
    assert bodies[0]["max_tokens"] == 23
    assert ledger.snapshot()["attempts"][0]["usage"]["completion_tokens"] == 1


def test_retry_limit_applies_to_every_role(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    calls = []
    def fake(*args):
        calls.append(1)
        return "bad"
    monkeypatch.setattr(llm, "_call", fake)
    with budget.Budget(budget.Limits(max_retries=1)).scope() as ledger:
        with pytest.raises(llm.LLMError):
            llm.complete_json("summary", "s", "p", model="m", retries=9)
    assert len(calls) == ledger.snapshot()["calls"] == 2


def test_provider_ignoring_output_limit_stops_followup_calls(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PP_LLM_INPUT_USD_PER_M", "0")
    monkeypatch.setenv("PP_LLM_OUTPUT_USD_PER_M", "0")
    calls = []
    def fake(*args):
        calls.append(1)
        budget.record_usage({"prompt_tokens": 100, "completion_tokens": 30})
        return "{}"
    monkeypatch.setattr(llm, "_call", fake)
    with budget.Budget(budget.Limits(max_output_tokens=10)).scope() as ledger:
        with pytest.raises(budget.BudgetExceeded):
            llm.complete_json("summary", "s", "p", model="m")
        with pytest.raises(budget.BudgetExceeded):
            llm.complete_json("react", "s", "p", model="m")
    assert len(calls) == ledger.snapshot()["calls"] == 1


def test_missing_attempt_journal_cannot_reset_spend(tmp_path):
    path = tmp_path / "budget.json"
    with budget.Budget(path=path).scope() as ledger:
        with ledger.attempt("llm:react", "input", mock=True):
            pass
    path.with_suffix(".attempts.jsonl").unlink()
    with pytest.raises(budget.BudgetExceeded):
        budget.Budget(path=path)


def test_same_budget_cannot_run_in_two_scopes(tmp_path):
    path = tmp_path / "budget.json"
    first, second = budget.Budget(path=path), budget.Budget(path=path)
    with first.scope():
        with pytest.raises(budget.BudgetExceeded):
            with second.scope():
                pytest.fail("second execution must not acquire this run")


@pytest.fixture
def synthetic_service(tmp_path, monkeypatch):
    from ppservice import jobs
    from ppservice.db import Database
    from ppservice.survey import panel
    from test_svc_survey import FakeJev, make_settings, new_survey, new_user, QUESTION, OPTIONS
    from conftest import make_rows

    settings = make_settings(tmp_path, monkeypatch, PP_SURVEY_N=4)
    db = Database(settings.db_path)
    people = [{**p, "profile": p["persona"], "age_band": "30대", "capital": True} for p in make_rows(4)]
    monkeypatch.setattr(panel, "load", lambda **kwargs: (people, "synthetic-panel-v1"))
    uid = new_user(db)
    sid = new_survey(db, uid)
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    runner = jobs.JobRunner(db, settings, FakeJev())
    return settings, db, people, uid, sid, run, runner


def test_survey_records_identity_and_refuses_changed_partial(synthetic_service):
    from ppservice import jobs
    settings, db, people, uid, sid, run, runner = synthetic_service
    claimed = runner._claim()
    runner.run_one(*claimed)
    row = db.one("SELECT * FROM runs WHERE id=?", (run["id"],))
    assert row["status"] == "succeeded"
    result = json.loads(row["result"])
    assert len(result["input_hash"]) == 64 and result["budget"]["calls"] == 12
    people[0]["profile"] = "인물 자료가 수정되었습니다."
    with db.tx() as con:
        con.execute("UPDATE runs SET status='queued' WHERE id=?", (run["id"],))
    previous_calls = runner.evaluate.calls
    runner.run_one(*runner._claim())
    row = db.one("SELECT * FROM runs WHERE id=?", (run["id"],))
    assert row["status"] == "failed" and row["error_code"] == "input_changed"
    assert runner.evaluate.calls == previous_calls


def test_service_call_limit_is_terminal(synthetic_service):
    from dataclasses import replace
    from ppservice import jobs
    settings, db, people, uid, sid, run, runner = synthetic_service
    runner.settings = replace(settings, max_calls=2, threads=1)
    runner.run_one(*runner._claim())
    row = db.one("SELECT status, error_code FROM runs WHERE id=?", (run["id"],))
    assert row["status"] == "failed" and row["error_code"] == "budget_exceeded"
    assert runner.evaluate.calls == 2
    assert db.one("SELECT actual_usd FROM spend WHERE run_id=?", (run["id"],))["actual_usd"] is None


def test_deep_reserves_all_role_budget_before_running(synthetic_service):
    from ppservice import deep
    settings, db, people, uid, sid, run, runner = synthetic_service
    runner.run_one(*runner._claim())
    deep.request(db, settings, uid, run["id"])
    reserved = db.one("SELECT * FROM spend WHERE run_id=? AND input_tokens=-1", (run["id"],))
    assert reserved["reserved_usd"] == .5 and reserved["actual_usd"] is None
    deep.request(db, settings, uid, run["id"])
    assert len(db.all("SELECT * FROM spend WHERE run_id=? AND input_tokens=-1", (run["id"],))) == 1
