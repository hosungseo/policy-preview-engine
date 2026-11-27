"""Skill output contract at every public adapter, without paid model calls."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pp import api, cli, llm, mcp, public_rules, service
from pp.jobs import Jobs
from test_public_interfaces import fake_models, wait_job

# Keep this literal independent of the implementation: a translated/reworded notice is a regression.
NOTICE = "AI가 상상한 반응입니다. 사람 응답은 0명입니다. 여론도 통계도 아닙니다. 누구에게 무엇을 물을지 정하는 데만 쓰세요."
POLICY = "Published transport policy\n1. 교통비의 30%를 지원한다. 지원 신청은 지역 담당 부서에서 접수한다."
UNSAFE = [
    "찬성 70%", "찬반 분포 7:3", "열 명 중 일곱", "3개 집단이 같은 걱정", "반대 순위 1위",
    "리스크 점수 8점", "H/M/L", "상·중·하", "높음·보통·낮음", "🔴🟡🟢", "빨강",
    "+ / - / 0", "★★★★☆", "주된 반응", "반응이 많다", "집단 태그: 분노",
    "dominant reaction", "most groups support", "risk: high", "support ratio 0.8",
    "7 out of 10 people oppose", "찬성:7 반대:3", "3/4 support", "우려",
    "찬성 7 반대 3", "찬성 일곱 반대 셋",
]


def assert_notice(data):
    assert next(iter(data)) == "notice"
    assert data["notice"] == NOTICE


def assert_contract(data, unsafe):
    assert_notice(data)
    assert unsafe not in json.dumps(data, ensure_ascii=False)
    result = data.get("result", data)
    assert_notice(result)
    assert "30%" in json.dumps(result["clauses"], ensure_ascii=False)
    assert len(result["warnings"]) > 1
    forbidden = {"support", "oppose", "stance", "share", "rank", "ranking", "score", "rating",
                 "counts", "n", "mean", "frequency", "member_ids", "would_comment", "flags"}

    def walk(value):
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    # Counts and IDs in execution/selection receipts describe sampling, never votes.
    walk({k: v for k, v in result.items() if k not in {"selection", "execution_inputs"}})


@pytest.fixture
def malicious_models(fake_models, monkeypatch, request):
    unsafe = request.param
    original = llm._mock

    def call(task, system, prompt, model, timeout):
        data = json.loads(original(task, system, prompt))
        if task == "react":
            data.update(reason="분류: " + unsafe, suggestion=unsafe)
        elif task == "cluster":
            for item in data["issues"]:
                item.update(title=unsafe, summary=unsafe)
        elif task == "qa":
            for item in data["items"]:
                item.update(question=unsafe, answer=unsafe)
        return json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(service, "_api_transport", lambda keys: call)
    return unsafe


@pytest.mark.parametrize("malicious_models", UNSAFE, indirect=True)
def test_cli_output_contract(malicious_models, tmp_path, capsys):
    policy, output = tmp_path / "policy.md", tmp_path / "result.json"
    policy.write_text(POLICY)
    assert cli.main(["run", str(policy), "--sample", "12"]) == 0
    captured = capsys.readouterr()
    assert captured.err.splitlines()[0] == NOTICE
    assert_contract(json.loads(captured.out), malicious_models)
    assert cli.main(["run", str(policy), "--sample", "12", "--out", str(output)]) == 0
    assert_contract(json.loads(output.read_text()), malicious_models)


@pytest.mark.parametrize("malicious_models", UNSAFE, indirect=True)
def test_http_output_contract(malicious_models):
    with TestClient(api.create_app()) as client:
        started = client.post("/runs", json={"policy_text": POLICY, "sample": 12})
        assert started.status_code == 202
        assert_notice(started.json())
        state = wait_job(lambda rid: client.get("/runs/" + rid).json(), started.json()["id"])
        assert state["status"] == "completed", state
        assert_contract(state, malicious_models)


@pytest.mark.parametrize("malicious_models", UNSAFE, indirect=True)
def test_mcp_output_contract(malicious_models):
    jobs = Jobs()
    server = mcp.create_server(jobs)

    async def scenario():
        started = await server.call_tool("start_run", {"policy_text": POLICY, "sample": 12})
        assert not started.isError
        assert started.content[0].text.splitlines()[0] == NOTICE
        assert_notice(started.structuredContent)
        state = wait_job(jobs.get, started.structuredContent["id"])
        assert state["status"] == "completed", state
        result = await server.call_tool("get_run", {"id": state["id"]})
        assert result.content[0].text.splitlines()[0] == NOTICE
        assert_notice(result.structuredContent)
        assert len(result.content[0].text) <= 3000
        assert malicious_models not in json.dumps(result.structuredContent, ensure_ascii=False)
        assert result.content[0].text == result.structuredContent["summary"]["text"]
        full = await server.call_tool("get_run", {"id": state["id"], "view": "full"})
        assert_contract(full.structuredContent, malicious_models)
        assert json.loads(full.content[0].text.split("\n", 1)[1]) == full.structuredContent

    try:
        asyncio.run(scenario())
    finally:
        jobs.close()


@pytest.mark.parametrize("field", ["text", "label", "trigger_quote"])
def test_only_verbatim_source_quotes_keep_ratios(field):
    source = "지원 비율 30%"
    warnings = []
    assert public_rules.check_output({field: source}, source, warnings)[field] == source
    assert not warnings
    assert public_rules.check_output({"summary": source}, source, warnings)["summary"] != source
    assert public_rules.check_output({field: "지원 비율 70%"}, source, warnings)[field] != "지원 비율 70%"


def test_document_size_is_preserved():
    result = service.estimate(POLICY)
    assert_notice(result)
    assert result["policy_chars"] == len(POLICY)


def test_http_unexpected_error_has_notice(fake_models, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-provider-error")
    monkeypatch.setattr(service, "estimate", fail)
    with TestClient(api.create_app(), raise_server_exceptions=False) as client:
        response = client.post("/estimate", json={"policy_text": POLICY})
        assert response.status_code == 500
        assert_notice(response.json())
        assert "private-provider-error" not in response.text


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"], ["missing-command"]])
def test_cli_help_and_parser_errors_have_notice(arguments, capsys):
    with pytest.raises(SystemExit):
        cli.main(arguments)
    captured = capsys.readouterr()
    assert (captured.out or captured.err).splitlines()[0] == NOTICE
