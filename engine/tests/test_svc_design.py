"""Question design: elephant drafts, isolated goldfish reviews each candidate, rule lint runs too."""
import pytest
from fastapi.testclient import TestClient

from ppservice import auth
from ppservice.app import create_app
from ppservice.survey import design

from test_svc_survey import H, POLICY, FakeJev, make_settings


def test_goldfish_prompt_sees_only_the_notice_and_one_question():
    p = design.review_prompt("정책 문안", "이 개정안에 찬성하십니까?", ["찬성", "반대"])
    assert "정책 문안" in p and "이 개정안에 찬성하십니까?" in p
    assert "후보" not in p and "설계자" not in p  # nothing from the drafting side


def test_basis_must_be_quoted_from_the_text(monkeypatch):
    monkeypatch.setattr(design.llm, "complete_json", lambda *a, **k: {"candidates": [
        {"focus": "f", "question": "q1?", "options": ["찬성", "반대"], "basis": "월 지원 한도는 5만 원이다"},
        {"focus": "f", "question": "q2?", "options": ["찬성", "반대"], "basis": "문안에 없는 말"},
        {"focus": "f", "question": "q3?", "options": ["하나뿐"]}]})
    got = design.draft("t", POLICY)
    assert [c["question"] for c in got] == ["q1?", "q2?"]
    assert got[0]["basis"] and got[1]["basis"] == ""


@pytest.mark.needs_panel
def test_route_returns_reviewed_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    app = create_app(make_settings(tmp_path, monkeypatch), start_workers=False, evaluate=FakeJev())
    code = auth.add_user(app.state.db, "a@x.go.kr")
    with TestClient(app) as c:
        c.post("/api/login", json={"email": "a@x.go.kr", "code": code}, headers=H)
        out = c.post("/api/question-design", json={"title": "시내버스", "policy_text": POLICY}, headers=H).json()
        assert len(out["candidates"]) == 2
        first = out["candidates"][0]
        assert first["review"]["verdict"] in design.VERDICTS and first["review"]["paraphrase"]
        assert isinstance(first["lint"], list)
        assert c.post("/api/question-design", json={"policy_text": "짧음"}, headers=H).status_code == 422


@pytest.mark.needs_panel
def test_pilot_flags_order_shift_and_one_sidedness():
    calm = design.pilot("t", POLICY, "찬성하십니까?", ["찬성", "반대", "잘 모르겠다"], FakeJev(), n=20)
    assert calm["n"] > 0 and abs(sum(calm["percent"]) - 100) <= 2 and calm["shift_pp"] < design.SHIFT_PP
    shaky = design.pilot("t", POLICY, "찬성하십니까?", ["찬성", "반대", "잘 모르겠다"], FakeJev(reversal=0.3), n=20)
    assert shaky["shift_pp"] > design.SHIFT_PP and any("순서" in f for f in shaky["flags"])
    lopsided = design.pilot("t", POLICY, "q?", ["찬성", "반대"], FakeJev(reversal=0.0, age_effect=3.0), n=20)
    assert lopsided["notes"] and not any("한쪽" in f for f in lopsided["flags"])  # a note, never a ranking penalty
    down = design.pilot("t", POLICY, "q?", ["찬성", "반대"], FakeJev(fail=True), n=10)
    assert down["n"] == 0 and down["flags"]  # a pilot that failed says so, never "no flags"


@pytest.mark.needs_panel
def test_reviewer_rewrite_becomes_a_reviewed_candidate_and_best_is_ranked_first(monkeypatch):
    def fake(task, system, prompt, **k):
        if task == "question_draft":
            return {"candidates": [{"focus": "전체", "question": "이 좋은 개정안에 찬성하십니까?", "options": ["찬성", "반대"]}]}
        if "좋은 개정안" in prompt:
            return {"paraphrase": "p", "issues": [{"kind": "유도", "message": "‘좋은’"}], "verdict": "고쳐 쓰기",
                    "better": "이 개정안에 찬성하십니까?", "better_options": ["찬성", "반대", "잘 모르겠다"]}
        return {"paraphrase": "p", "issues": [], "verdict": "좋음", "better": ""}
    monkeypatch.setattr(design.llm, "complete_json", fake)
    out = design.propose("t", POLICY, evaluate=FakeJev(), pilot_n=10)
    first, second = out["candidates"]
    assert first["revised_from"] == "이 좋은 개정안에 찬성하십니까?" and first["options"][-1] == "잘 모르겠다"
    assert first["review"]["verdict"] == "좋음" and first.get("recommended") and not second.get("recommended")
    assert first["pilot"]["n"] > 0
