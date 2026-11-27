"""Contracts spanning onboarding, targeting, plans and the first result screen."""
import json

import pytest

from pp import config, mcp_copy, mcp_setup, public_rules, service
from pp.jobs import Jobs


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setenv("PP_PERSONA_DB", str(tmp_path / "missing.db"))
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(tmp_path / "missing.gz"))
    for key in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_plan_conditions_survive_summary_full_and_export(offline, tmp_path):
    conditions = [{"name": "고령 이용자", "age_min": 65}]
    jobs = Jobs()
    try:
        quote = jobs.estimate(mcp_copy.EXAMPLES["subway-free-ride"].text,
                              sample=12, conditions=conditions, limits={"max_cost_usd": 0})
        # Neither a caller mutation nor a changed override may alter the accepted plan.
        conditions[0]["age_min"] = 70
        with pytest.raises(service.RequestError, match="견적"):
            jobs.start_planned(plan_id=quote["plan_id"], conditions=conditions)
        started = jobs.start_planned(plan_id=quote["plan_id"])
        assert jobs.start_planned(plan_id=quote["plan_id"])["id"] == started["id"]
        jobs.close()
        full = jobs.get(started["id"])
        assert full["status"] == "completed", full
        result = full["result"]
        assert result["schema"] == "pp.run/4"
        assert result["estimate"]["target_conditions"][0]["age_min"] == 65
        summary = jobs.get(started["id"], view="summary")
        assert summary["mode"] == "mock" and summary["trial_notice"] in summary["summary"]["text"]
        assert summary["summary"]["grouping"] == result["grouping"]
        assert len(summary["summary"]["text"]) <= 3000
        for card in summary["summary"]["cards"]:
            row = next(row for row in result["who_to_ask"] if row["issue_id"] == card["issue_id"])
            assert card["groups"] == row["groups"][:3]
            assert card["contact_hints"] == row["venues"][:3]
            assert card["panel_scope"] == row["panel_scope"]
        assert any(row["route"] for row in summary["summary"]["missing_perspectives"])
        saved = jobs.save_review(started["id"], str(tmp_path / "review.json"))
        assert saved["format"] == "pp.run/4"
        assert json.loads((tmp_path / "review.json").read_text()) == result
    finally:
        jobs.close()


def test_trial_works_without_repository_policy_files(offline, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    assert mcp_setup.check_setup()["free_trial_available"]
    result = mcp_setup.try_example("subway-free-ride")
    assert result["status"] == "completed" and result["cost_usd"] == 0
    assert result["result"]["mode"] == "archived"


def test_collective_reaction_prose_survives_but_named_requests_stay_blocked():
    text = "사람의 반응과 주민의 입장을 확인한다."
    assert public_rules.input_problem(text) is None
    warnings = []
    assert public_rules.check_output(text, "", warnings) == text
    assert not warnings
    for text in ("홍길동의 반응", "김철수 입장", "홍길동 의원의 반응", "장관의 반응"):
        assert public_rules.input_problem(text) is not None
