"""Free end-to-end checks: real engine, real sampling, fake model responses only."""
import asyncio
import json
import io
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import urllib.error

import pytest
from fastapi.testclient import TestClient

from pp import analyze_llm, api, budget, cli, jev, llm, bundle_db as portable, service
from pp.jobs import Jobs
from pp.public_rules import NOTICE

POLICY = "도시철도 이용 지원 정책안\n1. 무임승차 기준을 70세로 올린다.\n가. 취약계층 교통비 지원 방안을 마련한다."
SECRET = "fake-key-must-never-appear-in-output"


@pytest.fixture
def fake_models(persona_db, monkeypatch):
    # This fixture exercises the real API adapter with an offline fake transport.
    # Genuine keyless mock mode is covered separately without transport patches.
    monkeypatch.setenv("PP_LLM_PROVIDER", "cli")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    def fake(task, system, prompt, model, timeout):
        budget.record_usage({"input_tokens": 0, "output_tokens": 0})
        return llm._mock(task, system, prompt)
    monkeypatch.setattr(service, "_api_transport", lambda credentials: fake)
    original_call = llm._call
    monkeypatch.setattr(llm, "_call", lambda task, system, prompt, model, timeout:
                        original_call(task, system, prompt, model, timeout) if llm._transport.get() is not None
                        else llm._mock(task, system, prompt))
    # Fail closed if any path accidentally escapes the fake transport.
    monkeypatch.setattr(service.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("External call forbidden"))


def assert_result(result, sample=12):
    assert result["schema"] == "pp.run/2"
    assert result["estimate"]["sample"] == sample
    assert not result["conditions"]["reaction_failures"]
    assert result["group_reactions"]
    assert result["conditions"]["source"]["license"] == "CC BY 4.0"
    assert result["clauses"] and result["issues"] and result["who_to_ask"]
    assert all(row["questions"] and row["groups"] for row in result["who_to_ask"])
    assert result["missing_perspectives"]
    assert {p["group"] for p in result["missing_perspectives"] if p["kind"] == "underheard_group"} == {
        c["group"] for c in result["outreach"]}
    assert result["notice"] == NOTICE
    assert not result["clarity"]["available"]
    assert "TYPESAFE_API_KEY" in result["clarity"]["reason"]
    assert SECRET not in json.dumps(result)
    assert "ci95" not in json.dumps(result)


def wait_job(get, run_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        state = get(run_id)
        if state["status"] in {"completed", "failed"}:
            return state
        time.sleep(.01)
    pytest.fail("job did not finish")


def test_cli_policy_file_to_result_file(fake_models, tmp_path, capsys):
    draft, out = tmp_path / "policy.md", tmp_path / "result.json"
    draft.write_text(POLICY)
    assert cli.main(["estimate", str(draft)]) == 0
    assert json.loads(capsys.readouterr().out)["sample"] == 200
    assert cli.main(["run", str(draft), "--sample", "12", "--out", str(out)]) == 0
    assert_result(json.loads(out.read_text()))
    captured = capsys.readouterr()
    assert not captured.out and "실행 전 예상" in captured.err
    assert SECRET not in captured.err
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes()


def test_http_policy_to_job_to_result(fake_models):
    with TestClient(api.create_app()) as client:
        body = {"policy_text": POLICY, "sample": 12}
        budget = client.post("/estimate", json=body)
        assert budget.status_code == 200
        response = client.post("/runs", json=body, headers={"X-Anthropic-Api-Key": SECRET})
        assert response.status_code == 202
        assert response.json()["estimate"] == budget.json()
        state = wait_job(lambda rid: client.get(f"/runs/{rid}").json(), response.json()["id"])
        assert state["status"] == "completed", state
        assert_result(state["result"])
        assert client.get("/runs/not-a-run").status_code == 404


def test_missing_keys_and_invalid_requests(fake_models, monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with TestClient(api.create_app()) as client:
        assert client.post("/estimate", json={"policy_text": POLICY}).status_code == 200
        missing = client.post("/runs", json={"policy_text": POLICY})
        assert missing.status_code == 400 and "ANTHROPIC_API_KEY" in missing.text
        for body in ({"policy_text": POLICY, "api_key": SECRET},
                     {"policy_text": POLICY, "sample": True}, {"policy_text": " "},
                     {"policy_text": POLICY, "sample": 5001}, {"policy_text": "x" * 30001}):
            response = client.post("/runs", json=body)
            assert response.status_code in {400, 422}
            assert SECRET not in response.text
    draft = tmp_path / "policy.md"
    draft.write_text(POLICY)
    assert cli.main(["run", str(draft)]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    with pytest.raises(service.RequestError):
        service.run_policy(POLICY, credentials=service.Credentials())


def test_jobs_do_not_store_keys_or_raw_failures(fake_models, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise RuntimeError("remote response echoed " + SECRET)
    monkeypatch.setattr(service, "run_policy", fail)
    jobs = Jobs()
    try:
        started = jobs.start(POLICY)
        state = wait_job(jobs.get, started["id"])
        assert state["status"] == "failed"
        assert SECRET not in json.dumps(jobs._runs)
        assert SECRET not in repr(service.Credentials(SECRET, SECRET))
        assert not capsys.readouterr().out
    finally:
        jobs.close()


def test_large_panel_grouping_keeps_original_members_and_examples(fake_models):
    reactions = [{"rid": f"r{i}", "support": 0, "reason": f"이유 {i}", "concerns": ["우려"],
                  "suggestion": f"실제 제안 {i}"} for i in range(1, 5001)]
    known = {r["rid"] for r in reactions}
    for groups in (analyze_llm.cluster_issues(reactions, "정책"),
                   analyze_llm.cluster_suggestions(reactions, "정책")):
        members = [rid for c in groups for rid in c["member_ids"]]
        assert set(members) == known
        assert len(members) == len(known)
    assert all(c["example"].startswith("실제 제안") for c in analyze_llm.cluster_suggestions(reactions, "정책"))


def test_consultation_questions_ask_the_resident(fake_models, monkeypatch):
    from pp import mock
    def qa(system, prompt):
        assert "담당자가 당사자에게" in prompt
        return mock._qa(system, prompt)
    monkeypatch.setitem(llm.MOCK, "qa", qa)
    assert_result(service.run_policy(POLICY, sample=12))


def test_request_credentials_are_isolated_in_reaction_threads(fake_models, monkeypatch):
    seen = {}
    def transport(keys):
        def call(task, system, prompt, model, timeout):
            if task == "react":
                expected = "key-A" if "문안A" in prompt else "key-B"
                assert keys.anthropic == expected
                seen[expected] = seen.get(expected, 0) + 1
            return llm._mock(task, system, prompt)
        return call
    monkeypatch.setattr(service, "_api_transport", transport)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.run_policy, POLICY + label, sample=12,
                               credentials=service.Credentials(key))
                   for label, key in (("문안A", "key-A"), ("문안B", "key-B"))]
        for future in futures:
            assert_result(future.result())
    assert seen == {"key-A": 12, "key-B": 12}
    assert llm._transport.get() is None
    assert jev._request_key.get() is None


def test_http_model_transport_keeps_key_in_headers_and_redacts_failures(monkeypatch):
    def respond(request, **kwargs):
        assert request.get_header("X-api-key") == SECRET
        assert SECRET.encode() not in request.data
        return io.BytesIO(json.dumps({"content": [{"type": "text", "text": '{"ok": true}'}]}).encode())
    monkeypatch.setattr(service.urllib.request, "urlopen", respond)
    call = service._api_transport(service.Credentials(SECRET))
    assert json.loads(call("react", "system", POLICY, service.MODEL, 5)) == {"ok": True}
    def fail(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.anthropic.com", 401, SECRET, {}, io.BytesIO(SECRET.encode()))
    monkeypatch.setattr(service.urllib.request, "urlopen", fail)
    with pytest.raises(llm.LLMError) as exc:
        call("react", "system", POLICY, service.MODEL, 5)
    assert SECRET not in str(exc.value)


def test_cli_model_failure_does_not_echo_provider_error(fake_models, monkeypatch, tmp_path, capsys):
    draft = tmp_path / "policy.md"
    draft.write_text(POLICY)
    def fail(*args, **kwargs):
        raise llm.LLMError("provider echoed " + SECRET)
    monkeypatch.setattr(service, "run_policy", fail)
    assert cli.main(["run", str(draft)]) == 2
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_jev_key_reaches_clarity_threads_without_disk_fallback(fake_models, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    seen = []
    def evaluate(state, questions, **kwargs):
        seen.append(jev.api_key())
        assert not jev.cache_enabled()
        return {"answers": {k: {"noul": .2} for k in questions}}
    monkeypatch.setattr(jev, "evaluate", evaluate)
    result = service.run_policy(POLICY, sample=12, credentials=service.Credentials(SECRET, "request-jev-key"))
    assert result["clarity"]["available"]
    assert "threshold" not in result["clarity"]
    assert "values" not in json.dumps(result["clarity"])
    assert "document_questions" in result["clarity"]
    assert len(seen) == len(result["clauses"]) + 1
    assert set(seen) == {"request-jev-key"}
    assert "request-jev-key" not in json.dumps(result)


@pytest.mark.needs_panel
def test_portable_bundle_build_and_real_provider(fake_models, tmp_path, monkeypatch):
    # Exercise the actual shipped 20k artifact, not a fake alternative engine.
    monkeypatch.delenv("PP_PERSONA_DB")
    first = portable.ensure()
    assert first == portable.ensure()
    result = service.run_policy(POLICY)
    assert_result(result, sample=200)
    assert result["conditions"]["source"]["population"] == 20000


@pytest.fixture
def fake_process_script(fake_models, tmp_path):
    script = tmp_path / "fake_process.py"
    script.write_text("from pp import service, llm\n"
                      "service._api_transport = lambda keys: lambda task, system, prompt, model, timeout: "
                      "llm._mock(task, system, prompt)\n"
                      "import urllib.request\n"
                      "def no_network(*args, **kwargs): raise RuntimeError('external network forbidden')\n"
                      "urllib.request.urlopen = no_network\n"
                      "import sys\n"
                      "if sys.argv[1] == 'mcp':\n"
                      "    from pp.mcp import main\n"
                      "    main()\n"
                      "else:\n"
                      "    from pp.cli import main\n"
                      "    raise SystemExit(main(sys.argv[1:]))\n")
    return script


def test_cli_subprocess(fake_process_script, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(POLICY)
    result = subprocess.run([sys.executable, str(fake_process_script), "run", str(draft), "--sample", "12"],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert_result(json.loads(result.stdout))
    assert SECRET not in result.stdout + result.stderr


@pytest.mark.parametrize("name,arguments", [
    ("estimate", {"policy_text": POLICY}),
    ("start_run", {"policy_text": POLICY}),
    ("get_run", {"id": "missing"}),
])
@pytest.mark.parametrize("extra", ["api_key", "anthropic_api_key", "TYPESAFE_API_KEY", "unexpected", SECRET])
def test_mcp_rejects_extra_arguments_before_execution(name, arguments, extra, monkeypatch, capsys, caplog):
    from pp.mcp import create_server

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid arguments must be rejected before tool execution")

    jobs = Jobs()
    monkeypatch.setattr(service, "estimate", forbidden)
    monkeypatch.setattr(jobs, "start", forbidden)
    monkeypatch.setattr(jobs, "get", forbidden)
    server = create_server(jobs)
    try:
        result = asyncio.run(server.call_tool(name, {**arguments, extra: SECRET}))
        assert result.isError
        assert "추가 인자" in result.structuredContent["error"]
        assert "키는 환경변수로 설정합니다(BYOK)" in result.structuredContent["error"]
        assert result.content[0].text.splitlines()[0] == NOTICE
        assert result.structuredContent["notice"] == NOTICE
        captured = capsys.readouterr()
        assert SECRET not in result.model_dump_json() + captured.out + captured.err + caplog.text
    finally:
        jobs.close()


def test_mcp_real_stdio_estimate_start_poll(fake_process_script):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        params = StdioServerParameters(command=sys.executable, args=[str(fake_process_script), "mcp"], env=dict(os.environ))
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert {"estimate", "start_run", "get_run", "check_setup", "try_example", "find_notice", "get_notice"} <= {t.name for t in tools.tools}
                # API keys must never be accepted in tool arguments/transcripts.
                assert all("api_key" not in json.dumps(t.inputSchema) for t in tools.tools)
                assert all(t.inputSchema["additionalProperties"] is False for t in tools.tools)
                for name, arguments, extra in [
                    ("estimate", {"policy_text": POLICY}, "seed"),
                    ("start_run", {"policy_text": POLICY}, "unexpected"),
                    ("get_run", {"id": "missing"}, "sample"),
                    ("estimate", {"policy_text": POLICY}, "api_key"),
                    ("start_run", {"policy_text": POLICY}, "api_key"),
                    ("get_run", {"id": "missing"}, "api_key"),
                ]:
                    rejected = await session.call_tool(name, {**arguments, extra: SECRET})
                    assert rejected.isError
                    assert "추가 인자" in rejected.structuredContent["error"]
                    assert "키는 환경변수로 설정합니다(BYOK)" in rejected.structuredContent["error"]
                    assert rejected.content[0].text.splitlines()[0] == NOTICE
                    assert rejected.structuredContent["notice"] == NOTICE
                    assert SECRET not in rejected.model_dump_json()
                budget = await session.call_tool("estimate", {"policy_text": POLICY, "sample": 12})
                assert not budget.isError
                assert budget.content[0].text.splitlines()[0] == NOTICE
                started = await session.call_tool("start_run", {"policy_text": POLICY, "sample": 12})
                assert not started.isError
                assert started.content[0].text.splitlines()[0] == NOTICE
                run_id = started.structuredContent["id"]
                async with asyncio.timeout(15):
                    while True:
                        response = await session.call_tool("get_run", {"id": run_id})
                        assert not response.isError
                        assert response.content[0].text.splitlines()[0] == NOTICE
                        state = response.structuredContent
                        if state["status"] in {"completed", "failed"}:
                            break
                        await asyncio.sleep(.01)
                assert state["status"] == "completed", state
                assert_result(state["result"])

    asyncio.run(scenario())
