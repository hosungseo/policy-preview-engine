"""Synthetic opinion preview: lint, panel, aggregation, runs and API with an injected fake Jev."""
import re
import threading

import pytest
from fastapi.testclient import TestClient

from pp.jev import JevError
from ppservice import auth, jobs
from ppservice.app import create_app
from ppservice.db import Database
from ppservice.settings import load
from ppservice.survey import aggregate, lint, panel
from ppservice.survey.run import PLACEBO, jev_questions, state_for

H = {"X-PP-Client": "web"}
POLICY = "만 70세 이상 시민에게 시내버스 요금을 전액 지원한다. 2027년 1월 1일부터 시행하며 월 지원 한도는 5만 원이다."
QUESTION = "만 70세 이상 시내버스 요금 전액 지원에 찬성하십니까?"
OPTIONS = ["찬성", "반대", "잘 모르겠다"]


class FakeJev:
    """Older people lean to o1. `reversal` moves o1 when options are reversed; `fail` raises for every call."""

    def __init__(self, reversal: float = 0.0, fail: bool = False, age_effect: float = 0.5):
        self.calls = 0
        self.lock = threading.Lock()
        self.reversal, self.fail, self.age_effect = reversal, fail, age_effect

    def __call__(self, state, questions, *, cache=True, retries=4, timeout=60, label="other"):
        with self.lock:
            self.calls += 1
        if self.fail:
            raise JevError("HTTP 503")
        m = re.search(r"성별·나이: \S+, (\d+)세", state["person"])
        age = int(m.group(1)) if m else 40
        p1 = min(0.9, max(0.1, 0.3 + self.age_effect * (age - 19) / 70))
        keys = list(questions["q"]["criteria"])
        if keys[0] != "o1":  # reversed arm
            p1 = min(0.95, p1 + self.reversal)
        rest = (1 - p1) / 2
        return {"model": "fake-jev", "usage": {"input_tokens": 900},
                "answers": {"q": {"type": "choice", "probabilities": {"o1": p1, "o2": rest, "o3": rest}}}}


def make_settings(tmp_path, monkeypatch, **env):
    base = {"PP_SERVICE_DATA": str(tmp_path / "svc"), "PP_WEB_OUT": str(tmp_path / "noweb"), "PP_SURVEY_N": "1200",
            "PP_SURVEY_THREADS": "4", "PP_JEV_PROVIDER": "mock"}
    base.update({k: str(v) for k, v in env.items()})
    for k, v in base.items():
        monkeypatch.setenv(k, v)
    return load()


@pytest.fixture
def env(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)
    db = Database(settings.db_path)
    return settings, db


def new_user(db, email="a@x.go.kr"):
    auth.add_user(db, email)
    return db.one("SELECT id FROM users WHERE email=?", (email,))["id"]


def new_survey(db, uid):
    import secrets

    from ppservice.db import now
    sid = "s_" + secrets.token_hex(4)
    with db.tx() as con:
        con.execute("INSERT INTO surveys(id, user_id, title, policy_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sid, uid, "시내버스 요금 지원", POLICY, now(), now()))
    return sid


def drain(runner):
    while True:
        claimed = runner._claim()
        if not claimed:
            return
        runner.run_one(*claimed)


# ---- lint

def test_lint_rules():
    codes = lambda q, o=OPTIONS: {f["code"] for f in lint.check(POLICY, q, o)}  # noqa: E731
    assert codes(QUESTION) == set()
    assert "election" in codes("다음 대선에서 어느 후보를 지지하십니까?")
    assert "double" in codes("요금 지원 및 노선 확대에 찬성하십니까?")
    assert "loaded" in codes("세금 낭비인 요금 지원에 찬성하십니까?")
    assert "premise" in codes("고령층 부담을 덜기 위해 요금을 지원하는 데 찬성하십니까?")
    assert "options_balance" in codes(QUESTION, ["매우 찬성", "찬성", "반대"])
    assert "options_neutral" in codes(QUESTION, ["찬성", "반대"])
    assert lint.blocked(lint.check(POLICY + " 담당 010-1234-5678", QUESTION, OPTIONS))
    assert lint.blocked(lint.check(POLICY, QUESTION, ["찬성"]))


# ---- panel

@pytest.mark.needs_panel
def test_panel_bundle_and_stratified_sample():
    people, version = panel.load()
    assert len(people) == 20000 and len(version.split("+")[0]) == 12
    assert {"uuid", "sex", "age", "age_band", "province", "capital", "profile"} <= set(people[0])
    a, b = panel.sample(people, 3000, 7), panel.sample(people, 3000, 7)
    assert [p["uuid"] for p in a] == [p["uuid"] for p in b] and len(a) == 3000
    share = lambda xs, f: sum(1 for p in xs if f(p)) / len(xs)  # noqa: E731
    for f in (lambda p: p["province"] == "서울", lambda p: p["age_band"] == "70세 이상", lambda p: p["sex"] == "여자"):
        assert abs(share(a, f) - share(people, f)) < 0.01


# ---- run shape

def test_requests_carry_question_and_reverse_only_order():
    q, r = jev_questions(OPTIONS), jev_questions(OPTIONS, reverse=True)
    # OPTIONS end with "잘 모르겠다", which stays last; only the substantive options swap.
    assert list(q["q"]["criteria"]) == ["o1", "o2", "o3"] and list(r["q"]["criteria"]) == ["o2", "o1", "o3"]
    assert q["q"]["criteria"] == r["q"]["criteria"]
    plain = jev_questions(["매우 그렇다", "보통", "전혀 아니다"], reverse=True)
    assert list(plain["q"]["criteria"]) == ["o3", "o2", "o1"]
    spec = {"title": "t", "policy_text": POLICY, "question": QUESTION}
    person = {"profile": "p"}
    assert state_for("main", spec, person)["question"] == QUESTION
    assert PLACEBO in state_for("placebo", spec, person)["policy"]["text"]
    assert PLACEBO not in state_for("main", spec, person)["policy"]["text"]


# ---- aggregation

def test_int_percent_sums_to_100():
    assert sum(aggregate.int_percent([0.333, 0.333, 0.334])) == 100
    assert aggregate.int_percent([0.5, 0.5]) == [50, 50]


def _answers(people, f_main, f_rev=None, f_pl=None):
    out = {"main": {}, "placebo": {}, "reversed": {}}
    for p in people:
        m = f_main(p)
        out["main"][p["uuid"]] = m
        out["placebo"][p["uuid"]] = (f_pl or f_main)(p)
        out["reversed"][p["uuid"]] = (f_rev or f_main)(p)
    return out


@pytest.mark.needs_panel
def test_group_split_reported_only_above_threshold():
    people = panel.sample(panel.load()[0], 3000, 1)
    spec = {"options": OPTIONS}
    big = lambda p: [0.8, 0.1, 0.1] if p["age_band"] == "70세 이상" else [0.4, 0.3, 0.3]  # noqa: E731
    r = aggregate.summarize(spec, people, _answers(people, big), [])
    assert r["splits"] and r["splits"][0]["axis"] == "연령대" and r["splits"][0]["high"] == "70세 이상"
    assert r["cautions"] and "유보 선택지" in r["cautions"][0]  # '잘 모르겠다' is among the options
    assert r["baseline"] is None and r["accuracy"]["payload"]["state"] == "not_applied"
    assert "±" not in r["summary_text"] and "실측 비교 검증 전이며 실제 조사로 확인이 필요합니다." in r["summary_text"]
    assert sum(r["percent"]) == 100 and "실제 여론조사 아님" in r["summary_text"] and "국민" not in r["summary_text"]
    small = lambda p: [0.52, 0.24, 0.24] if p["sex"] == "남자" else [0.50, 0.25, 0.25]  # noqa: E731
    r = aggregate.summarize(spec, people, _answers(people, small), [])
    assert r["splits"] == [] and r["next_action"]["kind"] == "real_survey"
    assert r["addons"] == []
    r = aggregate.summarize(spec, people, _answers(people, small), [], panel_version="abc123def456+addons-housing.finance-0a1b2c3d")
    assert [a["title"] for a in r["addons"]] == ["주거", "가계 살림"]
    assert any("애드온 2종(주거, 가계 살림)" in c and "실측보다 크게" in c for c in r["cautions"])


@pytest.mark.needs_panel
def test_unstable_and_placebo_shift():
    people = panel.sample(panel.load()[0], 1000, 2)
    spec = {"options": OPTIONS}
    base = lambda p: [0.5, 0.25, 0.25]  # noqa: E731
    r = aggregate.summarize(spec, people, _answers(people, base, f_rev=lambda p: [0.6, 0.2, 0.2],
                                                   f_pl=lambda p: [0.47, 0.265, 0.265]), [])
    assert r["unstable"] and r["reversal_shift_pp"] == 10.0 and r["placebo_shift_pp"] == 3.0
    assert r["next_action"]["kind"] == "fix_question"


# ---- runs

@pytest.mark.needs_panel
def test_run_end_to_end_with_fake_jev(env):
    settings, db = env
    fake = FakeJev()
    runner = jobs.JobRunner(db, settings, fake)
    uid = new_user(db)
    sid = new_survey(db, uid)
    run, created = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    again, created2 = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    assert created and not created2 and run["id"] == again["id"]
    drain(runner)
    row = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (run["id"],)))
    assert row["status"] == "succeeded" and row["done"] == row["total"] == 3600 and fake.calls == 3600
    res = row["result"]
    assert res["n"] == 1200 and res["splits"] and res["splits"][0]["high"] == "70세 이상"
    assert row["jev_model"] == "fake-jev" and row["panel_version"]
    assert db.one("SELECT ROUND(SUM(actual_usd), 4) AS s FROM spend")["s"] > 0


def test_concurrent_submits_one_run(env):
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    out = []
    ts = [threading.Thread(target=lambda: out.append(jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len({r["id"] for r, _ in out}) == 1 and sum(c for _, c in out) == 1


def test_election_question_blocked(env):
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    with pytest.raises(jobs.IntakeError) as e:
        jobs.submit(db, settings, uid, sid, "다음 총선에서 어느 정당을 지지하십니까?", OPTIONS)
    assert e.value.status == 422 and any(f["code"] == "election" for f in e.value.findings)


def test_limits(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch, PP_DAILY_RUNS=1)
    db = Database(settings.db_path)
    runner = jobs.JobRunner(db, settings, FakeJev())
    uid = new_user(db)
    jobs.submit(db, settings, uid, new_survey(db, uid), QUESTION, OPTIONS)
    drain(runner)
    with pytest.raises(jobs.IntakeError) as e:
        jobs.submit(db, settings, uid, new_survey(db, uid), QUESTION, OPTIONS)
    assert e.value.code == "daily_limit"
    settings2 = make_settings(tmp_path / "b", monkeypatch, PP_DAILY_BUDGET_USD="0.001")
    db2 = Database(settings2.db_path)
    uid2 = new_user(db2)
    with pytest.raises(jobs.IntakeError) as e:
        jobs.submit(db2, settings2, uid2, new_survey(db2, uid2), QUESTION, OPTIONS)
    assert e.value.code == "budget_exceeded"


@pytest.mark.needs_panel
def test_model_down_fails_and_retry_reuses_paid_answers(env, monkeypatch):
    settings, db = env
    monkeypatch.setattr(jobs.Runner, "sleep", lambda self, s: None)
    uid = new_user(db)
    sid = new_survey(db, uid)
    flaky = FakeJev()
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    # first 700 answers arrive, then the model goes down
    real = flaky.__call__

    def go(*a, **k):
        if flaky.calls >= 700:
            flaky.fail = True
        return real(*a, **k)
    runner = jobs.JobRunner(db, settings, go)
    drain(runner)
    row = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (run["id"],)))
    assert row["status"] == "failed" and row["error_code"] == "model_unavailable" and row["error_message"]
    paid = db.one("SELECT COUNT(*) AS n FROM answers WHERE run_id=?", (run["id"],))["n"]
    assert paid >= 600
    fresh = FakeJev()
    new = jobs.retry(db, settings, uid, run["id"])
    drain(jobs.JobRunner(db, settings, fresh))
    assert db.one("SELECT status FROM runs WHERE id=?", (new["id"],))["status"] == "succeeded"
    assert fresh.calls == 3600 - paid  # nothing paid twice


def test_retry_keeps_future_and_reuses_answers(env, monkeypatch):
    """A retried "5년 뒤 보기" run must keep its flag, so the spec hash matches and the paid answers are copied."""
    if not panel.future_available():
        pytest.skip("life history / forecast not built")
    settings, db = env
    monkeypatch.setattr(jobs.Runner, "sleep", lambda self, s: None)
    uid = new_user(db)
    sid = new_survey(db, uid)
    flaky = FakeJev()
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS, future=True)
    real = flaky.__call__

    def go(*a, **k):
        if flaky.calls >= 700:
            flaky.fail = True
        return real(*a, **k)
    drain(jobs.JobRunner(db, settings, go))
    assert db.one("SELECT status FROM runs WHERE id=?", (run["id"],))["status"] == "failed"
    paid = db.one("SELECT COUNT(*) AS n FROM answers WHERE run_id=?", (run["id"],))["n"]
    fresh = FakeJev()
    new = jobs.retry(db, settings, uid, run["id"])
    assert new["spec"]["future"] is True
    drain(jobs.JobRunner(db, settings, fresh))
    row = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (new["id"],)))
    assert row["status"] == "succeeded" and row["result"]["future"] is not None
    assert fresh.calls == row["total"] - paid  # nothing paid twice


@pytest.mark.needs_panel
def test_restart_resumes_without_repaying(env):
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    runner = jobs.JobRunner(db, settings, FakeJev())
    run_id, attempt = runner._claim()
    r = jobs.Runner(db, settings, run_id, attempt, uid, threading.Event())
    people = panel.sample(panel.load()[0], 1200, jobs.json.loads(db.one("SELECT spec FROM runs").__getitem__("spec"))["seed"])
    for p in people[:250]:
        r.save_answer("main", p["uuid"], [0.5, 0.25, 0.25], 900)
    assert runner.recover() == 1
    fake = FakeJev()
    drain(jobs.JobRunner(db, settings, fake))
    assert db.one("SELECT status FROM runs").__getitem__("status") == "succeeded" and fake.calls == 3600 - 250


def test_delete_during_run_cancels(env):
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    runner = jobs.JobRunner(db, settings, FakeJev())
    claimed = runner._claim()
    with db.tx() as con:
        con.execute("DELETE FROM surveys WHERE id=?", (sid,))
    runner.run_one(*claimed)
    assert db.one("SELECT COUNT(*) AS n FROM answers")["n"] == 0


# ---- API

@pytest.fixture
def api(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch)
    app = create_app(settings, start_workers=False, evaluate=FakeJev())
    codes = {e: auth.add_user(app.state.db, e) for e in ("a@x.go.kr", "b@x.go.kr")}
    return app, codes


def login(app, codes, email):
    c = TestClient(app)
    assert c.post("/api/login", json={"email": email, "code": codes[email]}, headers=H).status_code == 200
    return c


@pytest.mark.needs_panel
def test_api_flow_isolation_and_lint(api):
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    assert a.post("/api/lint", json={"policy_text": POLICY, "question": "세금 낭비인 지원에 찬성?", "options": OPTIONS},
                  headers=H).json()["findings"][0]["code"] == "loaded"
    bad = a.post("/api/surveys", json={"title": "", "policy_text": "짧음"}, headers=H)
    assert bad.status_code == 422
    sid = a.post("/api/surveys", json={"title": "시내버스", "policy_text": POLICY}, headers=H).json()["id"]
    blocked = a.post(f"/api/surveys/{sid}/runs", json={"question": "대선 후보 지지도는?", "options": OPTIONS}, headers=H)
    assert blocked.status_code == 422 and blocked.json()["error"]["findings"]
    run = a.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}, headers=H).json()["run"]
    drain(app.state.runner)
    got = a.get(f"/api/runs/{run['id']}").json()["run"]
    assert got["status"] == "succeeded" and got["result"]["percent"]
    survey = TestClient(app, cookies=a.cookies).get(f"/api/surveys/{sid}").json()
    assert survey["runs"][0]["id"] == run["id"]
    b = login(app, codes, "b@x.go.kr")
    assert b.get("/api/surveys").json()["surveys"] == []
    for path in (f"/api/surveys/{sid}", f"/api/runs/{run['id']}"):
        assert b.get(path).status_code == 404
    assert b.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}, headers=H).status_code == 404
    assert b.delete(f"/api/surveys/{sid}", headers=H).status_code == 404
    assert a.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}).status_code == 403
    assert TestClient(app).get(f"/api/surveys/{sid}").status_code == 401
    assert a.delete(f"/api/surveys/{sid}", headers=H).status_code == 200
    assert app.state.db.one("SELECT COUNT(*) AS n FROM answers")["n"] == 0


def test_addons_are_on_by_default_selectable_and_change_the_version(monkeypatch):
    import pytest
    from pp import life_context
    from ppservice.survey import panel
    if not panel.CONTEXT.exists() or not panel.BUNDLE.exists():
        pytest.skip("panel bundle or life context not built")
    plain, v_plain = panel.load(addons="off")
    full, v_full = panel.load(addons="all")
    some, v_some = panel.load(addons="finance,welfare")
    assert v_full.startswith(v_plain + "+addons-all-") and v_some.startswith(v_plain + "+addons-finance.welfare-")
    assert len(full) == len(plain) == len(some)
    assert "[공공통계로 배정한 생활 여건" in full[0]["profile"] and "[공공통계로" not in plain[0]["profile"]
    assert all("종교:" not in p["profile"].split("[공공통계로")[-1] for p in some[:200])
    monkeypatch.setenv("PP_PANEL_ADDONS", "bogus")
    with pytest.raises(ValueError):
        panel.addons_setting()
    monkeypatch.delenv("PP_PANEL_ADDONS", raising=False)
    assert panel.addons_setting() == life_context.CORE_ADDONS
    assert set(panel.addons_setting("반려동물 등록제를 의무화합니다")) == set(life_context.CORE_ADDONS) | {"pet"}
    assert set(panel.addons_setting("공공도서관 운영 시간을 늘립니다")) == set(life_context.CORE_ADDONS) | {"culture"}
    core_version = panel.load()[1]
    assert life_context.addons_from_version(core_version) == life_context.CORE_ADDONS
    assert life_context.addons_from_version(v_full) == life_context.ALL_ADDONS
    assert life_context.addons_from_version(v_plain) == ()
    from ppservice.survey import aggregate
    view = aggregate.addons_view(v_some)
    assert [a["name"] for a in view] == ["finance", "welfare"] and view[0]["title"] == "가계 살림"
    monkeypatch.setenv("PP_PANEL_ADDONS", "all")
    assert panel.addons_setting("아무 정책") == life_context.ALL_ADDONS
    monkeypatch.setenv("PP_PANEL_ADDONS", "off")
    assert panel.addons_setting() == ()
    monkeypatch.delenv("PP_PANEL_ADDONS")
    monkeypatch.setattr(panel, "CONTEXT", panel.CONTEXT.with_name("missing.jsonl.gz"))
    assert panel.addons_setting() == ()


def test_future_pair_adds_two_arms_and_a_cohort_view(env):
    import pytest
    from ppservice.survey.run import FUTURE_ARMS
    if not panel.future_available():
        pytest.skip("life history / forecast not built")
    settings, db = env
    fake = FakeJev()  # older people lean to o1, so the 2030 arm (everyone five years older) must move o1 up
    runner = jobs.JobRunner(db, settings, fake)
    uid = new_user(db)
    sid = new_survey(db, uid)
    run, created = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS, future=True)
    assert created and run["spec"]["future"] is True and run["total"] == 5 * 1200
    assert run["estimate_usd"] > jobs.estimate_usd({**run["spec"], "future": False}, 1200)
    drain(runner)
    row = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (run["id"],)))
    assert row["status"] == "succeeded"
    arms = {a["arm"]: a["n"] for a in db.all("SELECT arm, COUNT(*) AS n FROM answers WHERE run_id=? GROUP BY arm", (run["id"],))}
    assert set(arms) == set(ARMS_ALL := ("main", "placebo", "reversed", *FUTURE_ARMS))
    assert arms["future"] == arms["future_base"] < 1200 and row["total"] == 3 * 1200 + 2 * arms["future"] == row["done"]
    fut = row["result"]["future"]
    assert fut["year"] == 2030 and fut["n"] == arms["future"] and fut["dead"] + fut["n"] == 1200
    assert fut["shift_pp"] > 0 and fut["now_percent"][0] < fut["future_percent"][0]
    assert fut["format_shift_pp"] == 0.0  # the fake reads only the age, so the state block alone moves nothing
    assert fut["changed_n"] > 0 and fut["age_groups"] and all(g["shift_pp"] > 0 for g in fut["age_groups"])
    assert any("5년 뒤 보기" in c for c in row["result"]["cautions"])
    # a plain run has no future block and no extra arms
    sid2 = new_survey(db, uid)
    run2, _ = jobs.submit(db, settings, uid, sid2, QUESTION, OPTIONS)
    drain(runner)
    res2 = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (run2["id"],)))
    assert res2["result"]["future"] is None and res2["total"] == 3600


# ---- "대상 규칙으로 나눠 보기"

@pytest.mark.needs_panel
def test_summarize_unchanged_by_compare_groups():
    """Snapshot taken before compare_groups() was extracted from summarize(): the output must stay byte-identical.
    The attribution block added later is left out of the digest; tests/test_attribution_labels.py checks it."""
    import hashlib
    import json
    people = panel.sample(panel.load()[0], 3000, 1)
    spec = {"options": OPTIONS}
    big = lambda p: [0.8, 0.1, 0.1] if p["age_band"] == "70세 이상" else [0.4, 0.3, 0.3]  # noqa: E731
    small = lambda p: [0.52, 0.24, 0.24] if p["sex"] == "남자" else [0.50, 0.25, 0.25]  # noqa: E731
    digest = lambda r: hashlib.sha256(json.dumps({k: v for k, v in r.items() if k != "attribution"},  # noqa: E731
                                                 ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    assert digest(aggregate.summarize(spec, people, _answers(people, big), [])) == "d6b5db04a856d4b6"
    assert digest(aggregate.summarize(spec, people, _answers(people, small), [])) == "37ac8c9677556ee1"
    c = aggregate.compare_groups([p["uuid"] for p in people[:500]], [p["uuid"] for p in people[500:1000]],
                                 *(_answers(people, small)[a] for a in ("main", "placebo", "reversed")), 3, 0)
    assert c["diff"] == -aggregate.compare_groups([p["uuid"] for p in people[500:1000]], [p["uuid"] for p in people[:500]],
                                                  *(_answers(people, small)[a] for a in ("main", "placebo", "reversed")), 3, 0)["diff"]


def test_rule_view_threshold_and_counts():
    """Controlled inputs: hand-made states and answers, so the counts, the sampling term and the sign are checked as numbers."""
    import math
    import random
    rng = random.Random(3)
    people = [{"uuid": f"u{i:04d}", "age": 30 + i % 40, "province": "서울", "sex": "남자", "age_band": "30대", "capital": True}
              for i in range(3000)]
    states, answers = {}, {a: {} for a in ("main", "placebo", "reversed", "future_base", "future")}
    N_UND, N_MISSING, N_DEAD = 36, 20, 150
    for i, p in enumerate(people):
        fits = i < 600                       # the first 600 fit the rule in both years
        now = {"age": 30, "province": "서울", "marital": "미혼", "working": True, "income_q": 1 if fits else 4,
               "income_amt": 1500.0 if fits else 4000.0}
        then = {**now, "age": 35}
        if 600 <= i < 600 + N_UND:           # unknown income in both years
            now, then = {**now, "working": None, "income_amt": None}, {**then, "working": None, "income_amt": None}
        alive = True
        if 700 <= i < 700 + N_MISSING:
            then, alive = None, None
        elif 800 <= i < 800 + N_DEAD:
            then, alive = None, False
        states[p["uuid"]] = {"now": now, "then": then, "alive": alive}
        base = [0.6, 0.2, 0.2] if fits else [0.5, 0.25, 0.25]
        answers["main"][p["uuid"]] = answers["placebo"][p["uuid"]] = answers["reversed"][p["uuid"]] = base
        answers["future_base"][p["uuid"]] = base
        wobble = rng.uniform(-0.3, 0.3) if fits else 0.0   # only the fitting group moves, by varying amounts
        answers["future"][p["uuid"]] = [min(0.95, max(0.05, base[0] + wobble)), 0.05, 0.05]
    rule = {"income_max_manwon": 2000, "working": True, "note": "가구소득 기준은 패널에 없음"}
    v = aggregate.rule_view(people, answers, 3, 0, rule, states, control_pp=1.0, format_pp=2.0, top_label="찬성")
    assert v["y2025"] == {"n": 600, "pct": 20, "undetermined": N_UND, "total": 3000}
    assert v["y2030"]["total"] == 3000 - N_DEAD and v["y2030"]["undetermined"] == N_UND + N_MISSING and v["y2030"]["n"] == 600
    assert v["main_split"]["in"]["n"] == 600 and v["main_split"]["diff_pp"] == 10.0 and v["main_split"]["distinguishable"]
    g = v["future_split"]["in"]
    pairs = [p["uuid"] for p in people[:600]]
    diffs = [answers["future"][u][0] - answers["future_base"][u][0] for u in pairs]
    mean = sum(diffs) / 600
    sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / 600)
    assert g["sampling_pp"] == round(100 * aggregate.Z_MULTI * sd / math.sqrt(600), 1)
    assert g["threshold_pp"] == round(max(aggregate.FLOOR_PP, 1.0, 2.0, 100 * aggregate.Z_MULTI * sd / math.sqrt(600)), 1)
    assert v["future_split"]["out"]["shift_pp"] == 0.0 and v["future_split"]["out"]["sampling_pp"] == 0.0
    assert v["rule_text"] == "개인 근로·사업소득 연 2,000만 원 이하 · 일함"
    assert v["copy_text"].startswith("입력 규칙: 개인 근로·사업소득 연 2,000만 원 이하 · 일함. 이 규칙에 맞는 합성 인물(실제 대상 인원 아님): 2025년 상태로 600명(20%)")
    assert v["copy_text"].endswith("규칙에 넣지 못한 기준: 가구소득 기준은 패널에 없음.") and "대상자" not in v["copy_text"]
    assert v["age_bands_2030"] == [{"group": "30대", "n": 600}]
    # a narrow rule: too few people on each side
    narrow = aggregate.rule_view(people, answers, 3, 0, {"age_min": 19, "age_max": 20}, states, 1.0, 2.0, "찬성")
    assert narrow["main_split"] is None and narrow["main_small"] == "0명이라 비교하지 않습니다"
    assert narrow["future_split"]["in"] is None and "비교하지 않습니다" in narrow["future_split"]["in_small"]


def test_rule_view_splits_finished_run(env):
    if not panel.future_available():
        pytest.skip("life history / forecast not built")
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS, future=True)
    drain(jobs.JobRunner(db, settings, FakeJev()))
    before = {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("runs", "spend")}
    stored = db.one("SELECT result FROM runs WHERE id=?", (run["id"],))["result"]
    v = jobs.rule_view_for_run(db, uid, run["id"], {"working": True})
    assert v["y2025"]["n"] > 0 and v["y2025"]["total"] == 1200
    assert v["y2030"]["total"] >= v["future_split"]["in"]["n"] + (v["future_split"]["out"] or {"n": 0})["n"]
    assert v["main_split"]["in"]["n"] <= v["y2025"]["n"] and set(v["main_split"]) == {"in", "out", "diff_pp", "threshold_pp", "parts", "distinguishable"}
    assert set(v["future_split"]["in"]) == {"n", "now_top", "future_top", "shift_pp", "threshold_pp", "sampling_pp", "distinguishable"}
    assert v["future_split"]["in"]["n"] <= v["y2030"]["n"] and v["age_bands_2030"] and v["rule_text"] == "일함"
    narrow = jobs.rule_view_for_run(db, uid, run["id"], {"age_min": 19, "age_max": 24, "capital": True, "income_max_manwon": 1500})
    assert narrow["main_split"] is None and "비교하지 않습니다" in narrow["main_small"]
    assert db.one("SELECT result FROM runs WHERE id=?", (run["id"],))["result"] == stored
    assert {t: db.one(f"SELECT COUNT(*) AS n FROM {t}")["n"] for t in ("runs", "spend")} == before


def test_rule_validation_and_errors(env):
    if not panel.future_available():
        pytest.skip("life history / forecast not built")
    settings, db = env
    uid = new_user(db)
    sid = new_survey(db, uid)
    for bad, word in (({}, "하나는"), ({"age_min": 40, "age_max": 30}, "나이 하한"), ({"income_min_manwon": 3000, "income_max_manwon": 1000}, "소득 하한"),
                      ({"working": True, "note": "x" * 201}, "메모"), ({"age_min": 5}, "19~110"), ({"working": "yes"}, "일함 여부")):
        with pytest.raises(jobs.IntakeError) as e:
            jobs.validate_rule(bad)
        assert e.value.code == "invalid_rule" and e.value.status == 422 and word in e.value.message
    assert jobs.validate_rule({"working": True, "note": "  메모 "}) == {"income_max_manwon": None, "income_min_manwon": None, "working": True,
                                                                        "age_min": None, "age_max": None, "capital": None, "note": "메모"}
    plain, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS)
    with pytest.raises(jobs.IntakeError) as e:
        jobs.rule_view_for_run(db, uid, plain["id"], {"working": True})   # not finished yet
    assert e.value.code == "not_applicable" and e.value.status == 409
    drain(jobs.JobRunner(db, settings, FakeJev()))
    with pytest.raises(jobs.IntakeError) as e:
        jobs.rule_view_for_run(db, uid, plain["id"], {"working": True})   # finished, but no "5년 뒤 보기"
    assert e.value.code == "not_applicable"
    sid2 = new_survey(db, uid)
    run, _ = jobs.submit(db, settings, uid, sid2, QUESTION, OPTIONS, future=True)
    drain(jobs.JobRunner(db, settings, FakeJev()))
    with pytest.raises(jobs.IntakeError) as e:
        jobs.rule_view_for_run(db, uid, run["id"], {"age_min": 40, "age_max": 30})
    assert e.value.code == "invalid_rule"
    with pytest.raises(jobs.IntakeError) as e:
        jobs.rule_view_for_run(db, uid + 1, run["id"], {"working": True})
    assert e.value.code == "not_found"
    import json
    row = db.one("SELECT result FROM runs WHERE id=?", (run["id"],))
    result = json.loads(row["result"])
    kept = result["future"]["version"]
    jobs.reaggregate(db)
    assert json.loads(db.one("SELECT result FROM runs WHERE id=?", (run["id"],))["result"])["future"]["version"] == kept
    result["future"]["version"] = "00000000"
    with db.tx() as con:
        con.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), run["id"]))
    with pytest.raises(jobs.IntakeError) as e:
        jobs.rule_view_for_run(db, uid, run["id"], {"working": True})
    assert e.value.code == "data_changed" and e.value.status == 409


def test_rule_api_roundtrip(api):
    if not panel.future_available():
        pytest.skip("life history / forecast not built")
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    sid = a.post("/api/surveys", json={"title": "시내버스", "policy_text": POLICY}, headers=H).json()["id"]
    run = a.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS, "future": True}, headers=H).json()["run"]
    drain(app.state.runner)
    ok = a.post(f"/api/runs/{run['id']}/rule", json={"working": True, "note": "시도 기준은 메모로"}, headers=H)
    assert ok.status_code == 200 and ok.json()["rule_view"]["y2025"]["n"] > 0 and ok.json()["rule_view"]["rule"]["note"] == "시도 기준은 메모로"
    bad = a.post(f"/api/runs/{run['id']}/rule", json={"age_min": 40, "age_max": 30}, headers=H)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_rule"
    assert a.post(f"/api/runs/{run['id']}/rule", json={"working": "x"}, headers=H).status_code == 422  # pydantic shape error
    b = login(app, codes, "b@x.go.kr")
    assert b.post(f"/api/runs/{run['id']}/rule", json={"working": True}, headers=H).status_code == 404


@pytest.mark.needs_panel
def test_survey_list_carries_the_latest_headline(api):
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    sid = a.post("/api/surveys", json={"title": "시내버스", "policy_text": POLICY}, headers=H).json()["id"]
    assert a.get("/api/surveys").json()["surveys"][0]["headline"] is None
    a.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}, headers=H)
    drain(app.state.runner)
    head = a.get("/api/surveys").json()["surveys"][0]["headline"]
    assert head["option"] in OPTIONS and 0 <= head["percent"] <= 100 and isinstance(head["unstable"], bool)


@pytest.mark.needs_panel
def test_demo_login_serves_one_shared_account_without_a_code(tmp_path, monkeypatch):
    settings = make_settings(tmp_path, monkeypatch, PP_DEMO_LOGIN=1)
    app = create_app(settings, start_workers=False, evaluate=FakeJev())
    c = TestClient(app)
    assert c.get("/api/config").json()["demo_login"] is True
    assert c.get("/api/me").json() == {"email": auth.DEMO_EMAIL}
    assert c.get("/api/surveys", headers=H).status_code == 200
    # A second visitor is the same account, and the account is created only once.
    assert TestClient(app).get("/api/me").json() == {"email": auth.DEMO_EMAIL}
    assert app.state.db.one("SELECT COUNT(*) AS n FROM users")["n"] == 1


@pytest.mark.needs_panel
def test_demo_login_is_off_unless_asked_for(tmp_path, monkeypatch):
    monkeypatch.delenv("PP_DEMO_LOGIN", raising=False)
    settings = make_settings(tmp_path, monkeypatch)
    app = create_app(settings, start_workers=False, evaluate=FakeJev())
    c = TestClient(app)
    assert c.get("/api/config").json()["demo_login"] is False
    assert c.get("/api/me").status_code == 401
    assert app.state.db.one("SELECT COUNT(*) AS n FROM users")["n"] == 0
