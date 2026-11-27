"""Upstage endpoint choice: UPSTAGE_BASE_URL > PP_UPSTAGE_REGION > global. No request leaves the machine here."""
import json

import pytest

from pp import jev


@pytest.fixture
def upstage(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("UPSTAGE_API_KEY", "solar_test_key")
    monkeypatch.delenv("PP_JEV_URL", raising=False)
    return monkeypatch


def test_default_is_the_global_endpoint(upstage):
    assert jev.api_url() == "https://api.upstage.ai/v1/systemone" == jev.UPSTAGE_API


@pytest.mark.parametrize("value", ["kr", "KR", " kr "])
def test_kr_region(upstage, value):
    upstage.setenv("PP_UPSTAGE_REGION", value)
    assert jev.api_url() == "https://kr.api.upstage.ai/v1/systemone"


def test_global_region_is_the_default(upstage):
    upstage.setenv("PP_UPSTAGE_REGION", "global")
    assert jev.api_url() == "https://api.upstage.ai/v1/systemone"


def test_base_url_wins_over_region_and_trailing_slashes_are_dropped(upstage):
    upstage.setenv("PP_UPSTAGE_REGION", "global")
    upstage.setenv("UPSTAGE_BASE_URL", "https://kr.api.upstage.ai/v1/")
    assert jev.api_url() == "https://kr.api.upstage.ai/v1/systemone"
    upstage.setenv("UPSTAGE_BASE_URL", "https://example.upstage.ai/v1///")
    assert jev.api_url() == "https://example.upstage.ai/v1/systemone"


def test_empty_values_fall_back_to_the_default(upstage):
    upstage.setenv("UPSTAGE_BASE_URL", "  ")
    upstage.setenv("PP_UPSTAGE_REGION", "")
    assert jev.api_url() == "https://api.upstage.ai/v1/systemone"


@pytest.mark.parametrize("value", ["jp", "korea", "us-east"])
def test_unknown_region_is_an_error(upstage, value):
    upstage.setenv("PP_UPSTAGE_REGION", value)
    with pytest.raises(jev.JevError, match="PP_UPSTAGE_REGION"):
        jev.api_url()


@pytest.mark.parametrize("value", ["http://kr.api.upstage.ai/v1", "kr.api.upstage.ai/v1", "https://"])
def test_base_url_must_be_https(upstage, value):
    upstage.setenv("UPSTAGE_BASE_URL", value)
    with pytest.raises(jev.JevError, match="UPSTAGE_BASE_URL"):
        jev.api_url()


def test_pp_jev_url_still_cannot_move_the_upstage_key(upstage):
    upstage.setenv("PP_JEV_URL", "https://untrusted.example/systemone")
    upstage.setenv("PP_UPSTAGE_REGION", "kr")
    assert jev.api_url() == "https://kr.api.upstage.ai/v1/systemone"


def test_typesafe_ignores_the_upstage_settings(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.delenv("PP_JEV_URL", raising=False)
    monkeypatch.setenv("UPSTAGE_BASE_URL", "https://kr.api.upstage.ai/v1")
    monkeypatch.setenv("PP_UPSTAGE_REGION", "nowhere")
    assert jev.api_url() == jev.TYPESAFE_API


def test_request_goes_to_the_kr_endpoint_with_the_upstage_key(upstage):
    upstage.setenv("PP_UPSTAGE_REGION", "kr")
    seen = {}

    def fake_post(url, body, *, headers, timeout):
        seen["url"], seen["auth"] = url, headers.get("Authorization")
        return json.dumps({"answers": {"q": {"type": "noul", "noul": 0.5}}, "usage": {"input_tokens": 3}})

    upstage.setattr(jev.net, "post", fake_post)
    jev.evaluate({"persona": "p"}, {"q": {"type": "noul", "instructions": "x"}}, cache=False)
    assert seen == {"url": "https://kr.api.upstage.ai/v1/systemone", "auth": "Bearer solar_test_key"}


def test_bad_region_fails_before_any_request(upstage):
    upstage.setenv("PP_UPSTAGE_REGION", "jp")
    calls = []
    upstage.setattr(jev.net, "post", lambda *a, **k: calls.append(a))
    with pytest.raises(jev.JevError, match="PP_UPSTAGE_REGION"):
        jev.evaluate({"persona": "p"}, {"q": {"type": "noul", "instructions": "x"}}, cache=False)
    assert calls == []
