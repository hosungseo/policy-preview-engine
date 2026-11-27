"""First use must finish offline, without credentials or a downloaded panel."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time

import pytest

from pp import budget, config, mcp_setup, public_rules, service
from pp.jobs import Jobs
from pp.mcp import create_server


@pytest.fixture
def offline(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "TYPESAFE_API_KEY", "PP_LLM_API_KEY", "UPSTAGE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setenv("PP_PERSONA_SOURCE", "bundle")
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(tmp_path / "missing.jsonl.gz"))
    monkeypatch.setenv("PP_PERSONA_DB", str(tmp_path / "missing.db"))
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path / "missing-data"))

    def forbidden(*args, **kwargs):
        pytest.fail("An offline trial attempted external execution")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(service, "_api_transport", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)


@pytest.mark.parametrize("name", mcp_setup.EXAMPLES)
def test_all_engine_examples_pass_rules(name):
    policy = json.loads((config.REPO_ROOT / "engine" / "policies" / f"{name}.json").read_text())
    service.validate(policy["title"] + "\n" + policy["text"])


@pytest.mark.parametrize("text", [
    "보건복지부장관이 정한다.", "기재부장관이 정하는 사항", "○○부장관이 정한다.",
    "전통시장·노동시장 지원", "사람의 반응을 모아 현장 질문을 만든다.", "주민의 입장과 시민의 반응을 확인한다.", "청년 주택시장 안정 대책", "정보공개 청구 시 비공개 대상 정보를 줄인다.",
    "선거관리위원회 사무 지원 예산", "중앙선거관리위원회 조직 개편",
])
def test_legal_terms_are_not_individuals(text):
    assert public_rules.input_problem(text) is None


@pytest.mark.parametrize("text,fragment,column", [
    ("정책안\n홍길동 의원의 반응", "홍길동 의원", 1),
    ("정책안\n이 문안은 선거 공약", "선거", 7),
    ("정책안\n내부 검토 문안", "내부 검토", 1),
])
def test_rejections_show_word_and_location(text, fragment, column):
    problem = public_rules.input_problem(text)
    assert fragment in problem
    assert f"줄 2, 열 {column}" in problem
    with pytest.raises(service.RequestError) as exc:
        service.validate(text)
    assert mcp_setup.error_payload(exc.value)["code"] == "input_rejected"


@pytest.mark.parametrize("name", mcp_setup.EXAMPLES)
def test_try_example_completes_offline_even_in_real_mode(offline, monkeypatch, name):
    monkeypatch.setenv("PP_LLM_PROVIDER", "cli")
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-use-or-show-this-key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "must-not-use-or-show-this-jev-key")
    before = dict(os.environ)
    started = time.monotonic()
    response = mcp_setup.try_example(name)
    assert time.monotonic() - started < 60
    assert dict(os.environ) == before
    assert response["status"] == "completed" and response["cost_usd"] == 0
    result = response["result"]
    assert result["result_label"] == "공개 예시 · 보관 결과"
    assert result["budget"]["cost_usd"] == 0 and result["budget"]["cost_status"] == "known"
    assert result["mode"] == "archived" and result["archive"]["sha256"]
    assert result["issues"] and result["who_to_ask"]
    assert "NVIDIA" in json.dumps(result, ensure_ascii=False)
    assert "must-not-use-or-show" not in json.dumps(result)
    assert not mcp_setup.mock_mode()
    assert mcp_setup.demo_panel() is None


def test_mock_start_run_without_panel_or_keys(offline):
    jobs = Jobs()
    try:
        state = jobs.start("대중교통 이용 지원 정책안\n교통비를 지원한다.", sample=12, limits={"max_cost_usd": 0})
        jobs.close()
        result = jobs.get(state["id"])
        assert result["status"] == "completed", result
        assert result["result"]["budget"]["cost_usd"] == 0
        assert result["result"]["mode"] == "mock"
    finally:
        jobs.close()


def test_setup_and_missing_key_panel_are_distinct(offline, monkeypatch):
    ready = mcp_setup.check_setup()
    assert ready["ready"] and ready["free_trial_available"]
    assert ready["mode"] == "mock" and not ready["panel"]["available"]
    monkeypatch.setenv("PP_LLM_PROVIDER", "cli")
    state = mcp_setup.check_setup()
    assert not state["ready"]
    assert {p["code"] for p in state["problems"]} == {"missing_model_key", "panel_not_ready"}
    jobs = Jobs()
    try:
        with pytest.raises(service.RequestError) as missing:
            jobs.start("교통비 지원 정책안")
        assert missing.value.code == "missing_model_key"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-unused")
        with pytest.raises(mcp_setup.SetupError) as panel:
            jobs.start("교통비 지원 정책안")
        assert panel.value.code == "panel_not_ready"
        assert not jobs._runs
    finally:
        jobs.close()


def test_budget_failure_code_and_safe_mcp_errors(offline):
    jobs = Jobs()
    try:
        started = jobs.start("교통비 지원 정책안", sample=12, limits={"max_calls": 1})
        jobs.close()
        failed = jobs.get(started["id"])
        assert failed["status"] == "failed" and failed["error_code"] == "budget_exceeded"
        assert failed["budget"]["cost_usd"] == 0
        server = create_server(jobs)

        async def scenario():
            for name, arguments, code in [
                ("get_run", {"id": "secret-unknown-id"}, "run_not_found"),
                ("estimate", {"policy_text": "홍길동 의원의 반응"}, "input_rejected"),
                ("try_example", {"example": "secret-unknown-example"}, "input_rejected"),
            ]:
                result = await server.call_tool(name, arguments)
                assert result.isError and result.structuredContent["code"] == code
                assert "secret-unknown" not in result.model_dump_json()
                for field in ("message", "next_action", "free_alternative"):
                    assert result.structuredContent[field]
            ready = await server.call_tool("check_setup", {})
            assert not ready.isError
            trial = await server.call_tool("try_example", {})
            assert not trial.isError and trial.structuredContent["cost_usd"] == 0

        asyncio.run(scenario())
    finally:
        jobs.close()


def test_errors_never_echo_secret_values(offline, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "홍길동 의원")
    assert "홍길동 의원" not in public_rules.input_problem("홍길동 의원의 반응")
    for exc in (KeyError("sensitive-id"), RuntimeError("sensitive-provider-response"), budget.BudgetExceeded("sensitive-response")):
        assert "sensitive" not in json.dumps(mcp_setup.error_payload(exc))


def test_genuine_stdio_without_transport_stub(tmp_path):
    """Start the shipped server; a Python audit hook rejects all socket connects."""
    from test_lawmaking import LIST_HTML, NOTICE_HTML
    notice_stub = (
        "from pp import lawmaking, mcp_notices\nfrom datetime import date\n"
        "class Today(date):\n    @classmethod\n    def today(cls): return cls(2026, 11, 27)\n"
        "mcp_notices.date = Today\n"
        f"pages = [('/gcom/ogLmPp/89312', {NOTICE_HTML!r}), ('/gcom/ogLmPp', {LIST_HTML!r})]\n"
        "lawmaking._get = lambda url, params=None: next(body for part, body in pages if part in url)\n"
    )
    script = tmp_path / "offline_server.py"
    script.write_text("import sys\n"
                      "def audit(event, args):\n"
                      "    if event == 'socket.connect': raise RuntimeError('network forbidden')\n"
                      "sys.addaudithook(audit)\n" + notice_stub + "from pp.mcp import main\nmain()\n")
    env = {k: v for k, v in os.environ.items() if not any(part in k for part in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update(PP_LLM_PROVIDER="mock", PP_JEV_PROVIDER="mock", PP_PERSONA_SOURCE="bundle",
               PP_PANEL_BUNDLE=str(tmp_path / "missing.gz"), PP_PERSONA_DB=str(tmp_path / "missing.db"))

    async def scenario():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async with stdio_client(StdioServerParameters(command=sys.executable, args=[str(script)], env=env)) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                assert not (await session.call_tool("check_setup", {})).isError
                notices = await session.call_tool("find_notice", {})
                assert not notices.isError and notices.structuredContent["items"]
                detail = await session.call_tool("get_notice", {"seq": notices.structuredContent["items"][0]["seq"]})
                assert not detail.isError and "개정이유" in detail.structuredContent["policy_text"]
                trial = await session.call_tool("try_example", {})
                assert not trial.isError and trial.structuredContent["mode"] == "archived"
                trial_id = trial.structuredContent["id"]
                trial_full = await session.call_tool("get_run", {"id": trial_id, "view": "full"})
                trial_saved = await session.call_tool("save_review", {"id": trial_id, "path": str(tmp_path / "trial.json")})
                assert not trial_full.isError and not trial_saved.isError
                assert json.loads((tmp_path / "trial.json").read_text()) == trial_full.structuredContent["result"]
                estimated = await session.call_tool("estimate", {"policy_text": "교통비 지원 정책안", "sample": 12})
                assert estimated.structuredContent["estimated_cost_usd"] == {"low": 0, "high": 0}
                started = await session.call_tool("start_run", {"plan_id": estimated.structuredContent["plan_id"]})
                assert not started.isError
                async with asyncio.timeout(30):
                    while True:
                        state = await session.call_tool("get_run", {"id": started.structuredContent["id"]})
                        assert not state.isError, state
                        if state.structuredContent["status"] in {"completed", "failed"}:
                            break
                        await asyncio.sleep(.01)
                assert state.structuredContent["status"] == "completed", state
                summary = state.structuredContent
                assert summary["mode"] == "mock" and summary["result_label"] == "체험(모의) 결과"
                assert summary["trial_notice"] in state.content[0].text
                full = await session.call_tool("get_run", {"id": started.structuredContent["id"], "view": "full"})
                assert full.structuredContent["result"]["budget"]["cost_usd"] == 0
                saved = await session.call_tool("save_review", {"id": started.structuredContent["id"], "path": str(tmp_path / "review.json")})
                assert not saved.isError and saved.structuredContent["format"] == "pp.run/3"
                assert json.loads((tmp_path / "review.json").read_text()) == full.structuredContent["result"]

    asyncio.run(scenario())
