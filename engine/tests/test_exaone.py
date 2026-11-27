"""EXAONE is fixed, local-only, and tested without contacting its API."""
import json

import pytest

from pp import config, llm


def _reply(content='{"ok": true}'):
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def test_exaone_uses_fixed_endpoint_model_and_local_boundary(monkeypatch):
    seen = []

    def fake_post(url, body, *, headers, timeout):
        seen.append({"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout})
        return _reply()

    monkeypatch.setenv("PP_LLM_PROVIDER", "exaone")
    monkeypatch.setenv("PP_EXAONE_LOCAL_ONLY", "1")
    monkeypatch.setenv("EXAONE_API_KEY", "exaone-secret")
    monkeypatch.setenv("PP_LLM_BASE_URL", "https://other.example/v1")
    monkeypatch.setenv("PP_LLM_API_KEY", "generic-secret")
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe-secret")
    monkeypatch.setenv("UPSTAGE_API_KEY", "upstage-secret")
    monkeypatch.setattr(llm.net, "post", fake_post)

    assert llm.complete_json("react", "system", "prompt", model=config.REACT_MODEL, retries=0, timeout=17) == {"ok": True}
    assert seen == [{
        "url": "https://api.exaone.ai/v1/chat/completions",
        "headers": {"Content-Type": "application/json", "User-Agent": "policy-preview/0.1",
                    "Authorization": "Bearer exaone-secret"},
        "body": {"model": "k-exaone_v2.5", "temperature": 0.7, "max_tokens": 16384,
                 "messages": [{"role": "system", "content": "system"}, {"role": "user", "content": "prompt"}]},
        "timeout": 17,
    }]
    assert llm.model_label(config.REACT_MODEL) == "k-exaone_v2.5"
    assert llm.model_label(config.SYNTH_MODEL) == "k-exaone_v2.5"


def test_exaone_requires_local_only_and_key_before_network(monkeypatch):
    calls = []
    monkeypatch.setenv("PP_LLM_PROVIDER", "exaone")
    monkeypatch.setattr(llm.net, "post", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(llm.time, "sleep", lambda _: None)

    with pytest.raises(llm.LLMError, match="PP_EXAONE_LOCAL_ONLY=1"):
        llm.complete_json("react", "s", "p", model=config.REACT_MODEL, retries=0)
    monkeypatch.setenv("PP_EXAONE_LOCAL_ONLY", "1")
    with pytest.raises(llm.LLMError, match="EXAONE_API_KEY"):
        llm.complete_json("react", "s", "p", model=config.REACT_MODEL, retries=0)
    assert calls == []


@pytest.mark.parametrize(("value", "message"), [("0", "between 1 and 16384"), ("16385", "between 1 and 16384"),
                                                    ("many", "must be an integer")])
def test_exaone_rejects_unbounded_or_invalid_token_limits(monkeypatch, value, message):
    monkeypatch.setenv("PP_EXAONE_MAX_TOKENS", value)
    with pytest.raises(llm.LLMError, match=message):
        llm._exaone_max_tokens()


def test_exaone_uses_configured_bounded_token_limit(monkeypatch):
    monkeypatch.setenv("PP_EXAONE_MAX_TOKENS", "512")
    assert llm._exaone_max_tokens() == 512
