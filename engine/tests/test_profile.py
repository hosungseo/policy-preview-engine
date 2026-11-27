"""The model setup badge reads the same settings the engine uses."""
import pytest

from ppservice import profile

SETUPS = {
    "mock": {"PP_LLM_PROVIDER": "mock", "PP_JEV_PROVIDER": "mock"},
    "korean": {"PP_LLM_PROVIDER": "exaone", "PP_JEV_PROVIDER": "upstage", "PP_UPSTAGE_REGION": "kr"},
    "local": {"PP_LLM_PROVIDER": "openai", "PP_LLM_BASE_URL": "http://127.0.0.1:8321/v1", "PP_LLM_MODEL": "locals/gemma",
              "PP_JEV_PROVIDER": "api", "PP_JEV_URL": "http://127.0.0.1:11434/v1/systemone", "PP_JEV_MODEL": "tev1:4b"},
    "global": {"PP_LLM_PROVIDER": "cli", "PP_JEV_PROVIDER": "api"},
    "mixed": {"PP_LLM_PROVIDER": "exaone", "PP_JEV_PROVIDER": "api"},
}


def _clear_profile_env(monkeypatch):
    for key in ("PP_LLM_PROVIDER", "PP_LLM_BASE_URL", "PP_LLM_MODEL", "PP_JEV_PROVIDER", "PP_JEV_URL", "PP_JEV_MODEL",
                "PP_MODEL_PROFILE", "PP_UPSTAGE_REGION", "UPSTAGE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize("kind", SETUPS)
def test_setup_is_inferred_from_where_models_run(monkeypatch, kind):
    _clear_profile_env(monkeypatch)
    for key, value in SETUPS[kind].items():
        monkeypatch.setenv(key, value)
    current = profile.current()
    assert current["kind"] == kind
    assert [c["kind"] for c in current["choices"]] == ["global", "korean", "local"]
    if kind == "local":
        assert (current["sentence"]["name"], current["decision"]["name"]) == ("gemma", "tev1:4b")


def test_korean_profile_never_claims_korean_without_confirmed_kr_region(monkeypatch):
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("PP_LLM_PROVIDER", "exaone")
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    # Default Upstage region is global -> must NOT be labelled korean even when PP_MODEL_PROFILE=korean.
    monkeypatch.setenv("PP_MODEL_PROFILE", "korean")
    got = profile.current()
    assert got["decision"]["where"] == "global"
    assert got["kind"] == "mixed"
    assert "글로벌" in got["decision"]["name"]

    # Explicit global UPSTAGE_BASE_URL beats PP_UPSTAGE_REGION=kr.
    monkeypatch.setenv("PP_UPSTAGE_REGION", "kr")
    monkeypatch.setenv("UPSTAGE_BASE_URL", "https://api.upstage.ai/v1")
    got_override_global = profile.current()
    assert got_override_global["decision"]["where"] == "global"
    assert got_override_global["kind"] == "mixed"

    # Explicit KR UPSTAGE_BASE_URL beats PP_UPSTAGE_REGION=global.
    monkeypatch.setenv("PP_UPSTAGE_REGION", "global")
    monkeypatch.setenv("UPSTAGE_BASE_URL", "https://kr.api.upstage.ai/v1")
    got_override_kr = profile.current()
    assert got_override_kr["decision"]["where"] == "korean"
    assert got_override_kr["kind"] == "korean"


def test_openai_upstage_global_url_is_not_labelled_korean(monkeypatch):
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("PP_LLM_PROVIDER", "openai")
    monkeypatch.setenv("PP_LLM_BASE_URL", "https://api.upstage.ai/v1")
    monkeypatch.setenv("PP_LLM_MODEL", "solar-pro")
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("PP_UPSTAGE_REGION", "kr")
    got = profile.current()
    assert got["sentence"]["where"] == "global"
    assert got["kind"] == "mixed"

    monkeypatch.setenv("PP_LLM_BASE_URL", "https://kr.api.upstage.ai/v1")
    got_kr = profile.current()
    assert got_kr["sentence"]["where"] == "korean"
    assert got_kr["kind"] == "korean"


def test_profiles_forbid_pre_announcement_private_drafts():
    for entry in profile.PROFILES.values():
        text = entry["use"]
        for forbidden in ("민감(S)", "기밀(C)", "발표 전 정책안처럼", "비공개 검토안·내부 자료가 섞인"):
            assert forbidden not in text
        assert "공개" in text


@pytest.mark.parametrize(("provider", "model", "expected"), [("upstage", "solar-decide", 10.7), ("api", "jev-latest", 11.0),
                                                            ("mock", "x", None), ("mock", "jev-latest", None)])
def test_holdout_matches_the_running_decision_model(monkeypatch, provider, model, expected):
    monkeypatch.setenv("PP_JEV_PROVIDER", provider)
    monkeypatch.setenv("PP_JEV_MODEL", model)
    got = profile.holdout()
    assert (got or {}).get("mae_pp") == expected


def test_flash_is_labelled_and_never_borrows_solar_decide_accuracy(monkeypatch):
    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("PP_LLM_PROVIDER", "exaone")
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("PP_JEV_MODEL", "solar-decide-flash")
    monkeypatch.setenv("PP_UPSTAGE_REGION", "kr")
    current = profile.current()
    assert current["decision"]["name"] == "Upstage Solar Decide Flash (solar-decide-flash · 한국 리전)"
    assert current["kind"] == "korean"
    assert profile.holdout() is None
    monkeypatch.setenv("PP_JEV_MODEL", "solar-decide")
    assert profile.current()["decision"]["name"].startswith("Upstage Solar Decide (")
    assert profile.holdout()["mae_pp"] == 10.7
