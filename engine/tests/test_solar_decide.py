import json

import pytest

from pp import jev
from ppservice import jobs, settings


def answer(value=0.5):
    return json.dumps({
        "answers": {"q": {"type": "noul", "noul": value}},
        "usage": {"input_tokens": 1000, "output_tokens": 12},
    }).encode()


def test_upstage_routes_solar_decide_request_and_only_uses_upstage_key(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("UPSTAGE_API_KEY", "solar_test_key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "must_not_leave_here")
    monkeypatch.setenv("PP_JEV_URL", "https://untrusted.example/systemone")
    captured = {}

    def fake_post(url, body, *, headers, timeout):
        captured["url"] = url
        captured["authorization"] = headers.get("Authorization")
        captured["body"] = json.loads(body)
        return answer().decode()

    monkeypatch.setattr(jev.net, "post", fake_post)
    out = jev.evaluate({"persona": "p"}, {"q": {"type": "noul", "instructions": "x"}}, cache=False)

    assert captured == {
        "url": "https://api.upstage.ai/v1/systemone",
        "authorization": "Bearer solar_test_key",
        "body": {
            "state": {"persona": "p"},
            "model": "solar-decide",
            "questions": {"q": {"type": "noul", "instructions": "x"}},
        },
    }
    assert out["usage"] == {"input_tokens": 1000, "output_tokens": 12}


def test_upstage_cost_is_dynamic_for_existing_jobs_import(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    assert jev.cost_usd(1_000_000) == 0.1
    # jobs reads the current provider price at calculation time.
    assert jobs.jev_price_per_m_input() == 0.1
    assert settings.jev_price_per_m_input() == 0.1


def test_cache_isolated_by_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PP_JEV_CACHE", "1")
    monkeypatch.setenv("PP_JEV_MODEL", "same-model")
    monkeypatch.setenv("TYPESAFE_API_KEY", "typesafe_key")
    calls = []

    def fake_post(url, body, *, headers, timeout):
        calls.append(url)
        return answer(len(calls) / 10).decode()

    monkeypatch.setattr(jev.net, "post", fake_post)
    q = {"q": {"type": "noul", "instructions": "x"}}

    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    first = jev.evaluate("state", q)
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("UPSTAGE_API_KEY", "solar_key")
    second = jev.evaluate("state", q)
    cached = jev.evaluate("state", q)

    assert calls == ["https://api.typesafe.ai/v1/systemone", "https://api.upstage.ai/v1/systemone"]
    assert first["answers"]["q"]["noul"] == 0.1
    assert second == cached
    assert second["answers"]["q"]["noul"] == 0.2


def test_upstage_without_key_is_unavailable(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.delenv("UPSTAGE_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("PP_JEV_URL", raising=False)

    assert not jev.available()
    with pytest.raises(jev.JevError, match="UPSTAGE_API_KEY is not set"):
        jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, cache=False)


def test_custom_endpoint_keeps_legacy_api_compatibility_without_typesafe_key(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("PP_JEV_URL", "http://127.0.0.1:9010/systemone")
    monkeypatch.setenv("PP_JEV_API_KEY", "custom_key")
    monkeypatch.setenv("TYPESAFE_API_KEY", "must_not_leave_here")
    captured = {}

    def fake_post(url, body, *, headers, timeout):
        captured.update(url=url, authorization=headers.get("Authorization"), body=json.loads(body))
        return answer().decode()

    monkeypatch.setattr(jev.net, "post", fake_post)
    assert jev.available()
    jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, cache=False)
    assert captured["url"] == "http://127.0.0.1:9010/systemone"
    assert captured["authorization"] == "Bearer custom_key"
    assert captured["body"]["model"] == "jev-latest"
