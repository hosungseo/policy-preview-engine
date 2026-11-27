"""Deep analysis continued from a survey run: same respondents, mock language model, real 20k panel bundle."""
import pytest
from fastapi.testclient import TestClient

from ppservice import auth, deep
from ppservice.app import create_app

from test_svc_survey import H, OPTIONS, POLICY, QUESTION, FakeJev, drain, login, make_settings


def drain_deep(app):
    while True:
        claimed = deep.claim(app.state.db)
        if not claimed:
            return
        deep.run_one(app.state.db, app.state.settings, *claimed)


@pytest.fixture
def api(tmp_path, monkeypatch):
    for k, v in {"PP_LLM_PROVIDER": "mock", "PP_DATA_DIR": str(tmp_path / "engine"), "PP_PERSONA_SOURCE": "bundle",
                 "PP_SEMANTIC": "off"}.items():
        monkeypatch.setenv(k, v)  # run_one sets the last two itself; monkeypatch restores them after the test
    settings = make_settings(tmp_path, monkeypatch, PP_DEEP_REP=24, PP_DEEP_AFF=6, PP_DEEP_JEV=40, PP_DEEP_ALT=12,
                             PP_DEEP_WORKERS=2, PP_DAILY_DEEPS=1)
    app = create_app(settings, start_workers=False, evaluate=FakeJev())
    codes = {e: auth.add_user(app.state.db, e) for e in ("a@x.go.kr", "b@x.go.kr")}
    return app, codes


def survey_run(client, app, drained=True):
    sid = client.post("/api/surveys", json={"title": "시내버스", "policy_text": POLICY}, headers=H).json()["id"]
    run = client.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}, headers=H).json()["run"]
    if drained:
        drain(app.state.runner)
    return sid, run["id"]


@pytest.mark.needs_panel
def test_deep_flow(api):
    app, codes = api
    a, b = login(app, codes, "a@x.go.kr"), login(app, codes, "b@x.go.kr")
    sid, rid = survey_run(a, app)
    assert a.get(f"/api/runs/{rid}/deep").json() == {"deep": None}
    assert b.get(f"/api/runs/{rid}/deep").status_code == 404
    assert b.post(f"/api/runs/{rid}/deep", headers=H).status_code == 404
    assert a.post(f"/api/runs/{rid}/deep").status_code == 403  # the client header is required for writes
    first = a.post(f"/api/runs/{rid}/deep", headers=H)
    assert first.status_code == 202 and first.json()["created"] and first.json()["deep"]["status"] == "queued"
    assert a.post(f"/api/runs/{rid}/deep", headers=H).json()["created"] is False
    assert a.get(f"/api/runs/{rid}/deep/bundle").status_code == 404
    drain_deep(app)
    got = a.get(f"/api/runs/{rid}/deep").json()["deep"]
    assert got["status"] == "succeeded", got
    res = got["result"]
    assert res["mock"] is True and res["counts"]["representative"] == 24 and res["counts"]["checked"] == 40
    assert [o["option"] for o in res["by_option"]] == OPTIONS
    assert sum(o["n"] for o in res["by_option"]) == res["counts"]["matched"] == 24  # every voice answered the survey
    assert abs(sum(o["share"] for o in res["by_option"]) - 1) < 0.01
    voice = next(v for o in res["by_option"] for v in o["voices"])
    assert voice["reason"] and 0 < voice["p"] <= 1 and voice["age"] >= 19
    assert res["issues"] and res["qa"] and res["limits"] and res["hearing"]["turns"] > 0
    full = a.get(f"/api/runs/{rid}/deep/bundle").json()["bundle"]
    # The people heard one by one come from the survey's own sample.
    answered = {r["uuid"] for r in app.state.db.all("SELECT uuid FROM answers WHERE run_id=? AND arm='main'", (rid,))}
    assert {p["uuid"] for p in full["personas"] if p["panel"] == "rep"} <= answered
    assert b.get(f"/api/runs/{rid}/deep/bundle").status_code == 404
    assert not deep.work_dir(app.state.settings, rid).exists()
    # daily limit (1), then deleting the survey removes the analysis with it
    _, rid2 = survey_run(a, app)
    over = a.post(f"/api/runs/{rid2}/deep", headers=H)
    assert over.status_code == 429 and over.json()["error"]["code"] == "daily_limit"
    assert a.delete(f"/api/surveys/{sid}", headers=H).status_code in (200, 204)
    assert app.state.db.one("SELECT COUNT(*) c FROM deeps")["c"] == 0


@pytest.mark.needs_panel
def test_deep_needs_finished_run_and_retries(api, monkeypatch):
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    _, rid = survey_run(a, app, drained=False)
    early = a.post(f"/api/runs/{rid}/deep", headers=H)
    assert early.status_code == 409 and early.json()["error"]["code"] == "not_ready"
    drain(app.state.runner)

    from pp import llm, pipeline
    real = pipeline.Run.stage_issues

    def broken(self):
        raise llm.LLMError("connection refused " + POLICY)

    monkeypatch.setattr(pipeline.Run, "stage_issues", broken)
    assert a.post(f"/api/runs/{rid}/deep", headers=H).status_code == 202
    drain_deep(app)
    failed = a.get(f"/api/runs/{rid}/deep").json()["deep"]
    assert failed["status"] == "failed" and failed["error_code"] == "llm_unavailable" and failed["error_message"]
    detail = app.state.db.one("SELECT error_detail FROM deeps WHERE run_id=?", (rid,))["error_detail"]
    assert POLICY not in detail
    work = deep.work_dir(app.state.settings, rid)
    assert (work / "reactions.json").exists()  # finished stages are kept for the retry
    monkeypatch.setattr(pipeline.Run, "stage_issues", real)
    again = a.post(f"/api/runs/{rid}/deep", headers=H).json()  # a retry does not count against the daily limit
    assert again["created"] and again["deep"]["status"] == "queued"
    drain_deep(app)
    assert a.get(f"/api/runs/{rid}/deep").json()["deep"]["status"] == "succeeded"
    assert not work.exists()


@pytest.mark.needs_panel
def test_deep_recover_and_cleanup(api):
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    _, rid = survey_run(a, app)
    a.post(f"/api/runs/{rid}/deep", headers=H)
    assert deep.claim(app.state.db) == (rid, 1)
    assert deep.recover(app.state.db) == 1
    assert app.state.db.one("SELECT status FROM deeps WHERE run_id=?", (rid,))["status"] == "queued"
    root = app.state.settings.data_dir / "deep-work"
    (root / "orphan").mkdir(parents=True)
    (root / rid).mkdir()
    assert deep.cleanup(app.state.db, app.state.settings) == 1
    assert (root / rid).exists() and not (root / "orphan").exists()


def test_coverage_marks_failed_steps_as_not_run():
    assert deep._coverage("확인", 85, 10) == {"step": "확인", "planned": 85, "done": 10, "status": "일부"}
    assert deep._coverage("확인", 40, 0)["status"] == "실행 안 됨"
    assert deep._coverage("확인", 40, None)["status"] == "실행 안 됨"
    assert deep._coverage("확인", 40, 40)["status"] == "완료"
    assert deep._coverage("확인", 0, 0) is None
