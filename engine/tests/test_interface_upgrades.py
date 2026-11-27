"""Public adapters preserve execution evidence while keeping prose qualitative."""
import asyncio
import io
import json

import pytest
from fastapi.testclient import TestClient

from pp import api, budget, jev, llm, mcp, provenance, service
from pp.jobs import Jobs
from test_public_interfaces import POLICY, SECRET, fake_models, wait_job


def evidence(result):
    assert result["input_hash"] == provenance.input_hash(result["execution_inputs"])
    assert result["selection"]["selected_count"] == 12
    assert len(set(result["selection"]["uuids"])) == 12
    assert result["selection"]["data"]["panel_version"] == result["conditions"]["panel_version"]
    assert result["budget"]["calls"] >= 14
    assert result["budget"]["cost_usd"] == 0
    assert result["attribution"]["sources"][0]["license"] == "CC BY 4.0"
    assert result["diagnostics"]["status"] == "qualitative_only"
    assert result["diagnostics"]["note"] in result["warnings"]
    assert SECRET not in json.dumps(result)


def test_http_and_mcp_keep_all_upgrade_evidence(fake_models):
    with TestClient(api.create_app()) as client:
        started = client.post("/runs", json={"policy_text": POLICY, "sample": 12})
        state = wait_job(lambda rid: client.get("/runs/" + rid).json(), started.json()["id"])
        assert state["status"] == "completed"
        evidence(state["result"])
    jobs = Jobs()
    server = mcp.create_server(jobs)
    try:
        started = asyncio.run(server.call_tool("start_run", {"policy_text": POLICY, "sample": 12}))
        state = wait_job(jobs.get, started.structuredContent["id"])
        got = asyncio.run(server.call_tool("get_run", {"id": state["id"], "view": "full"}))
        evidence(got.structuredContent["result"])
    finally:
        jobs.close()


def test_fingerprint_tracks_seed_text_limits_and_source(fake_models, persona_db):
    first = service.run_policy(POLICY, sample=12)
    evidence(first)
    assert first["input_hash"] == service.run_policy(POLICY, sample=12)["input_hash"]
    for args in ({"seed": 7}, {"limits": {"max_calls": 20}}):
        assert first["input_hash"] != service.run_policy(POLICY, sample=12, **args)["input_hash"]
    assert first["input_hash"] != service.run_policy(POLICY + "\n지원 절차를 공개한다.", sample=12)["input_hash"]
    assert service.estimate(POLICY)["input_hash"] != service.estimate(POLICY, limits={"max_calls": 1})["input_hash"]


@pytest.mark.parametrize("limits", [{"api_key": SECRET}, {"max_cost_usd": None},
    {"max_calls": True}, {"max_cost_usd": float("inf")}, {"max_retries": -1}])
def test_invalid_limits_rejected_without_echo(fake_models, limits):
    with pytest.raises(service.RequestError) as caught:
        service.run_policy(POLICY, limits=limits)
    assert SECRET not in str(caught.value)


def test_http_rejects_nested_key_and_remote_client(fake_models):
    with TestClient(api.create_app()) as client:
        for path in ("/estimate", "/runs"):
            response = client.post(path, json={"policy_text": POLICY, "limits": {"api_key": SECRET}})
            assert response.status_code == 400
            assert SECRET not in response.text
    with TestClient(api.create_app(), client=("203.0.113.5", 1234)) as client:
        assert client.post("/estimate", json={"policy_text": POLICY}).status_code == 403


def test_shared_call_cap_stops_before_later_stages_and_keeps_ledger(fake_models):
    jobs = Jobs()
    try:
        started = jobs.start(POLICY, sample=1, limits={"max_calls": 1})
        state = wait_job(jobs.get, started["id"])
        assert state["status"] == "failed"
        assert state["budget"]["calls"] == 1
        assert state["budget"]["limits"]["max_calls"] == 1
        assert SECRET not in json.dumps(state)
    finally:
        jobs.close()


@pytest.mark.parametrize("provider", ["anthropic", "mock"])
def test_zero_dollar_cap_blocks_transport_before_any_paid_attempt(fake_models, monkeypatch, provider):
    monkeypatch.setenv("PP_LLM_PROVIDER", provider)
    def forbidden(*args):
        pytest.fail("cost cap must stop before transport")
    monkeypatch.setattr(service, "_api_transport", lambda keys: forbidden)
    with pytest.raises(budget.BudgetExceeded) as caught:
        service.run_policy(POLICY, sample=1, limits={"max_cost_usd": 0})
    assert caught.value.budget_snapshot["calls"] == 0


def test_transport_token_limit_usage_and_full_system_reservation(monkeypatch):
    seen = []
    def respond(request, **kwargs):
        body = json.loads(request.data)
        seen.append(body)
        assert body["max_tokens"] == 7
        assert body["system"] == "system extra rules"
        return io.BytesIO(json.dumps({"content": [{"type": "text", "text": '{"ok":true}'}],
            "usage": {"input_tokens": 20, "output_tokens": 5}}).encode())
    monkeypatch.setattr(service.urllib.request, "urlopen", respond)
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    ledger = budget.Budget(budget.Limits(max_calls=1, max_output_tokens=7))
    with ledger.scope(), budget.use_prices({"llm": (1, 5)}), llm.use_transport(
            service._api_transport(service.Credentials(SECRET)), system_rules=" extra rules"):
        assert llm.complete_json("test", "system", "prompt", model=service.MODEL) == {"ok": True}
        with pytest.raises(budget.BudgetExceeded):
            llm.complete_json("test", "system", "prompt", model=service.MODEL)
    assert len(seen) == 1
    assert ledger.snapshot()["cost_usd"] == pytest.approx(45 / 1_000_000)
    assert ledger.snapshot()["cost_status"] == "known"


def test_optional_clarity_cannot_swallow_shared_budget_stop(fake_models, monkeypatch):
    def clarity(*args, **kwargs):
        with budget.attempt("jev:clarity", [], mock=True):
            pytest.fail("shared cap must stop before clarity transport")
    monkeypatch.setattr(service.jev_panel, "check_clarity", clarity)
    with pytest.raises(budget.BudgetExceeded) as caught:
        service.run_policy(POLICY, sample=1, credentials=service.Credentials(SECRET, "fake-jev"),
                           limits={"max_calls": 3})
    assert caught.value.budget_snapshot["calls"] == 3


def test_request_scope_fixed_typesafe_endpoint_and_no_fallback(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("PP_JEV_URL", "https://example.invalid/systemone")
    with jev.use_key("request-key"):
        assert jev.provider() == "api"
        assert jev.api_url() == jev.TYPESAFE_API
        assert jev.api_key() == "request-key"
        assert not jev.cache_enabled()
    assert jev.provider() == "upstage"


def test_request_transport_identity_overrides_ambient_provider(fake_models, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.delenv("PP_LLM_MODEL", raising=False)
    monkeypatch.delenv("PP_LLM_MODEL_REACT", raising=False)
    monkeypatch.delenv("PP_LLM_MODEL_SYNTH", raising=False)
    result = service.run_policy(POLICY, sample=12)
    evidence(result)
    assert result["execution_inputs"]["models"]["model"] == service.MODEL
    assert llm.provider() == "openai"


def test_reliability_warning_survives_both_adapters(fake_models):
    text = POLICY + "\n교통비 지원의 만족도를 확인한다."
    with TestClient(api.create_app()) as client:
        started = client.post("/runs", json={"policy_text": text, "sample": 12}).json()
        state = wait_job(lambda rid: client.get("/runs/" + rid).json(), started["id"])
        result = state["result"]
        assert result["diagnostics"]["reliability_findings"][0]["code"] == "reliability_subjective_topic"
        assert result["diagnostics"]["reliability_findings"][0]["message"] in result["warnings"]
