"""Remaining four regressions from the second first-use report."""
import asyncio
from copy import deepcopy

import pytest

from pp import archived_examples, mcp_copy, mcp_setup, summary_card
from pp.jobs import Jobs
from pp.mcp import create_server
from test_mcp_onboarding import offline


@pytest.mark.parametrize("example", archived_examples.EXAMPLES)
def test_example_interview_prompts_and_quotes_are_separate(example):
    result = archived_examples.load(example)
    original = deepcopy(result)
    summary = summary_card.build(result, "archive")
    assert result == original
    for card in summary["cards"]:
        row = next(r for r in result["who_to_ask"] if r["issue_id"] == card["issue_id"])
        quotes = [q["question"] for q in result["questions"] if q["issue_id"] == card["issue_id"]]
        assert card["questions"] == row["questions"]
        assert card["reaction_quotes"] == quotes[:1]
        assert set(card["questions"]).isdisjoint(quotes)
        assert all(q.endswith("?") and not q.startswith(("저는", "저희", "우리")) for q in card["questions"])
        assert "편집" in card["question_basis"]
        assert "먼저 물을 질문(편집 초안): " + card["questions"][0] in summary["text"]
        assert "보관 결과 인용: " + quotes[0] in summary["text"]
        assert card["contact_hints"]
        assert all(hint in summary["text"] for hint in card["contact_hints"])
    assert "원문 인용" in result["questions_notice"]


def test_second_and_third_cards_explicitly_mark_missing_contacts():
    summary = summary_card.build(archived_examples.load("subway-free-ride"), "archive")
    assert all(c["contact_hints"] == [summary_card.NO_CONTACT] for c in summary["cards"][1:])
    assert summary["text"].count("찾아갈 곳: " + summary_card.NO_CONTACT) == 2
    assert "방문 청취" in summary["cards"][0]["contact_hints"][0]
    assert "보관 결과 인용:" in mcp_copy.result_summary_markdown()
    assert summary_card.NO_CONTACT in mcp_copy.result_summary_markdown()


def test_contact_method_alone_is_still_a_contact_hint():
    result = {"who_to_ask": [{"groups": ["이용자"], "questions": ["어디에서 막히나요?"]}],
              "outreach": [{"group": "이용자", "where": "", "method": "전화 인터뷰"}]}
    assert summary_card.build(result, "run")["cards"][0]["contact_hints"] == ["전화 인터뷰"]
    result["outreach"] = [{"group": "이용자", "where": "", "method": ""}]
    assert summary_card.build(result, "run")["cards"][0]["contact_hints"] == [summary_card.NO_CONTACT]


def test_mock_summary_and_full_repeat_exact_first_line_for_assistant(offline):
    jobs = Jobs()
    try:
        started = jobs.start("교통비 지원 정책안", sample=12)
        jobs.close()
        server = create_server(jobs)
        for view in ("summary", "full"):
            response = asyncio.run(server.call_tool("get_run", {"id": started["id"], "view": view}))
            assert not response.isError
            first_line = response.content[0].text.splitlines()[0]
            assert first_line == mcp_setup.TRIAL_NOTICE
            assert "실제 여론이 아닙니다" in first_line
            assert all(word in first_line for word in ("0원", "구조", "가짜", "키"))
            guidance = response.structuredContent["assistant_guidance"]
            assert "첫 줄" in guidance and "그대로" in guidance
            assert guidance.endswith(first_line)
            assert response.content[1].text == guidance
    finally:
        jobs.close()


@pytest.mark.parametrize("already_started", [False, True])
def test_plan_id_rejected_as_run_id_with_recovery(offline, already_started):
    jobs = Jobs()
    try:
        server = create_server(jobs)
        quote = jobs.estimate("교통비 지원 정책안", sample=12)
        started = jobs.start_planned(plan_id=quote["plan_id"]) if already_started else None
        response = asyncio.run(server.call_tool("get_run", {"id": quote["plan_id"]}))
        assert response.isError
        assert response.structuredContent["code"] == "plan_id_as_run_id"
        assert response.structuredContent["message"] == "이 번호는 견적 번호입니다. start_run에 쓰세요."
        assert "start_run(plan_id=" in response.structuredContent["next_action"]
        assert quote["plan_id"] not in response.model_dump_json()
        recovered = jobs.start_planned(plan_id=quote["plan_id"])
        if started:
            assert recovered["id"] == started["id"]
        assert not asyncio.run(server.call_tool("get_run", {"id": recovered["id"]})).isError
        missing = asyncio.run(server.call_tool("get_run", {"id": "unknown-private-id"}))
        assert missing.structuredContent["code"] == "run_not_found"
        assert "plan_id" in missing.structuredContent["next_action"]
        assert "unknown-private-id" not in missing.model_dump_json()
        tools = asyncio.run(server.list_tools())
        get_run = next(t for t in tools if t.name == "get_run")
        assert "plan_id" in get_run.description
        assert "plan_id" in get_run.inputSchema["properties"]["id"]["description"]
    finally:
        jobs.close()
