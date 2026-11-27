"""Public rules exercised through real adapters with offline model stubs."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pp import api, cli, llm, mcp, public_rules, service
from pp.jobs import Jobs
from test_public_interfaces import POLICY, fake_models, wait_job

NOTICE = public_rules.NOTICE


@pytest.mark.parametrize("text", [
    "홍길동 의원은 어떻게 반응할까?", "김민수 씨의 반응", "현직 장관의 반응",
    "홍길동의 입장을 상상해", "President Jane Smith reaction",
    "선거 문안", "공개된 공약집", "정당 지지도를 알아봐", "candidate support campaign",
])
def test_blocked_input_never_reaches_model(text, monkeypatch):
    monkeypatch.setattr(service, "_api_transport", lambda *a: pytest.fail("Must stop before model setup"))
    for confirmed in (False, True):
        with pytest.raises(service.RequestError):
            service.run_policy(text, i_confirm_public=confirmed)
        with pytest.raises(service.RequestError):
            service.estimate(text, i_confirm_public=confirmed)


@pytest.mark.parametrize("marker", ["발표 전", "내부 검토", "미공개", "confidential", "internal draft"])
def test_public_confirmation_before_estimate_run_and_queue(marker, fake_models):
    text = marker + "\n" + POLICY
    with pytest.raises(service.RequestError, match="i-confirm-public"):
        service.estimate(text)
    with pytest.raises(service.RequestError):
        service.run_policy(text, sample=12)
    jobs = Jobs()
    try:
        with pytest.raises(service.RequestError):
            jobs.start(text)
        assert not jobs._runs
        state = jobs.start(text, sample=12, i_confirm_public=True)
        done = wait_job(jobs.get, state["id"])
        assert done["status"] == "completed"
        assert done["result"]["conditions"]["public_confirmed"] is True
    finally:
        jobs.close()


def test_cli_first_line_errors_confirmation_and_file(fake_models, tmp_path, capsys):
    draft, output = tmp_path / "draft.md", tmp_path / "result.json"
    draft.write_text("내부 검토\n" + POLICY)
    assert cli.main(["run", str(draft), "--out", str(output)]) == 2
    assert not output.exists()
    assert capsys.readouterr().err.splitlines()[0] == NOTICE
    assert cli.main(["run", str(draft), "--sample", "12", "--i-confirm-public", "--out", str(output)]) == 0
    assert NOTICE in output.read_text().splitlines()[0]
    assert json.loads(output.read_text())["notice"] == NOTICE
    assert capsys.readouterr().err.splitlines()[0] == NOTICE
    assert cli.main(["estimate", str(draft), "--i-confirm-public"]) == 0
    assert NOTICE in capsys.readouterr().out.splitlines()[0]


def test_http_notices_on_success_rejection_and_validation(fake_models):
    with TestClient(api.create_app()) as client:
        for path, body, status in [
            ("/estimate", {"policy_text": POLICY}, 200),
            ("/runs", {"policy_text": "공약집"}, 400),
            ("/runs", {"policy_text": "홍길동 의원의 반응"}, 400),
            ("/estimate", {"policy_text": "내부 검토\n" + POLICY}, 400),
            ("/runs", {"policy_text": "발표 전\n" + POLICY}, 400),
            ("/estimate", {"policy_text": POLICY, "i_confirm_public": "true"}, 422),
        ]:
            response = client.post(path, json=body)
            assert response.status_code == status
            assert response.json()["notice"] == NOTICE
            assert NOTICE in response.text.splitlines()[0]
        response = client.post("/runs", json={"policy_text": "내부 검토\n" + POLICY,
                                              "sample": 12, "i_confirm_public": True})
        assert response.status_code == 202
        done = wait_job(lambda rid: client.get("/runs/" + rid).json(), response.json()["id"])
        assert done["result"]["conditions"]["public_confirmed"]
        response = client.get("/runs/missing")
        assert response.status_code == 404 and NOTICE in response.text.splitlines()[0]


def test_mcp_notices_and_confirmation_including_sdk_errors(fake_models):
    jobs = Jobs()
    server = mcp.create_server(jobs)

    async def scenario():
        for name, arguments in [
            ("estimate", {"policy_text": "공개 공약집"}),
            ("start_run", {"policy_text": "홍길동 의원은?"}),
            ("estimate", {"policy_text": "발표 전\n" + POLICY}),
            ("start_run", {"policy_text": "내부 검토\n" + POLICY}),
            ("get_run", {"id": "missing"}),
            ("estimate", {"policy_text": POLICY, "sample": True}),
            ("unknown", {}),
        ]:
            result = await server.call_tool(name, arguments)
            assert result.isError
            assert NOTICE not in result.content[0].text
            assert result.structuredContent["notice"] == NOTICE
        started = await server.call_tool("start_run", {"policy_text": "내부 검토\n" + POLICY,
                                                        "sample": 12, "i_confirm_public": True})
        assert not started.isError
        state = wait_job(jobs.get, started.structuredContent["id"])
        assert state["status"] == "completed"
        assert state["result"]["conditions"]["public_confirmed"]
    try:
        asyncio.run(scenario())
    finally:
        jobs.close()


def test_generated_person_election_and_quantities_removed_everywhere(fake_models, monkeypatch):
    original = llm._mock
    unsafe = "홍길동 의원은 공약 지지도 70%로 다수가 찬성하고 7명이 반대한다."

    def malicious(task, system, prompt):
        data = json.loads(original(task, system, prompt))
        if task == "react":
            data["reason"] = unsafe
            data["suggestion"] = unsafe
        elif task == "cluster":
            for item in data["issues"]:
                item["title"] = unsafe
                item["summary"] = unsafe
        elif task == "qa":
            for item in data["items"]:
                item["question"] = unsafe
                item["answer"] = unsafe
        return json.dumps(data, ensure_ascii=False)

    monkeypatch.setattr(service, "_api_transport", lambda keys: lambda task, system, prompt, model, timeout:
                        malicious(task, system, prompt))
    result = service.run_policy(POLICY, sample=12)
    body = json.dumps(result, ensure_ascii=False)
    for fragment in ("홍길동", "공약", "70%", "다수", "7명"):
        assert fragment not in body
    assert len(result["warnings"]) > 1


def test_public_shape_has_no_vote_fields_counts_or_frequency_order(fake_models):
    result = service.run_policy(POLICY, sample=12)
    forbidden = {"counts", "n", "support", "stance", "share", "mean", "oppose", "silent", "direct",
                 "member_ids", "member_uuids", "groups_ranked", "rank", "lift", "would_comment"}

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
    clause_order = {c["id"]: i for i, c in enumerate(result["clauses"])}
    positions = [min((clause_order.get(r["segment_id"], len(clause_order)) for r in group["reactions"]),
                     default=len(clause_order)) for group in result["group_reactions"]]
    assert positions == sorted(positions)
    assert "방향 참고용" not in json.dumps(result, ensure_ascii=False)
    assert "70세" in json.dumps(result["clauses"], ensure_ascii=False)


@pytest.mark.parametrize("unsafe", ["대부분 찬성한다", "찬성 70%", "일곱 명이 반대", "반대 순위", "다수가 찬성", "가장 반대한다"])
def test_free_text_cannot_restore_vote_statistics(unsafe):
    warnings = []
    checked = public_rules.check_output({"summary": unsafe}, POLICY, warnings)
    assert checked["summary"] != unsafe
    assert warnings


def test_notice_is_the_exact_public_sentence():
    assert NOTICE == ("AI가 상상한 반응입니다. 사람 응답은 0명입니다. 여론도 통계도 아닙니다. "
                      "누구에게 무엇을 물을지 정하는 데만 쓰세요.")
