import pytest

from pp import llm


def test_extract_json_variants():
    assert llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.extract_json('설명입니다. {"a": {"b": 2}} 끝') == {"a": {"b": 2}}
    with pytest.raises(llm.LLMError):
        llm.extract_json("JSON이 없습니다")
    with pytest.raises(llm.LLMError):
        llm.extract_json("{broken: }")


def test_mock_provider_is_deterministic(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    prompt = "[정책]\n1. 무임승차 기준 연령을 단계적으로 올린다.\n[/정책]"
    one = llm.complete_json("react", "sys", prompt, model="haiku")
    two = llm.complete_json("react", "sys", prompt, model="haiku")
    assert one == two
    assert -2 <= one["support"] <= 2
    assert one["trigger_quote"] in "1. 무임승차 기준 연령을 단계적으로 올린다."


def test_retry_then_success_and_final_failure(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    calls = {"n": 0}

    def flaky(system, prompt):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"wrong": True}
        return {"value": 3}

    def need_value(d):
        if "value" not in d:
            raise ValueError("missing value")
        return d

    monkeypatch.setitem(llm.MOCK, "flaky", flaky)
    assert llm.complete_json("flaky", "s", "p", model="m", validate=need_value) == {"value": 3}
    assert calls["n"] == 2

    monkeypatch.setitem(llm.MOCK, "always_bad", lambda s, p: {"wrong": True})
    with pytest.raises(llm.LLMError):
        llm.complete_json("always_bad", "s", "p", model="m", validate=need_value, retries=1)


def test_unknown_mock_task(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    with pytest.raises(llm.LLMError):
        llm.complete_json("no_such_task", "s", "p", model="m", retries=0)


def test_lean_flags_disable_mcp_tools_and_user_settings():
    flags = " ".join(llm.LEAN_FLAGS)
    assert "--strict-mcp-config" in flags and "--tools" in flags and "--setting-sources project" in flags
    assert '"alwaysThinkingEnabled": false' in flags
    assert llm.CLI_ENV["MAX_THINKING_TOKENS"] == "0"
