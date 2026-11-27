"""Two-stage distribution contracts, offline slicing, and faithful archive numbers."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from pp import api, archived_examples, budget, cli, jev, mcp, numbers, service
from pp.jobs import Jobs
from test_public_interfaces import fake_models
from pp.trend_baseline import predict

POLICY = "공개 교통비 지원 정책안\n지역 주민의 교통비 지원 신청 절차를 정한다."


def row(i, *, panel="representative", age=65, stance="support", control=None, reverse=None):
    probabilities = {s: float(s == stance) for s in numbers.STANCES}
    return {"id": str(i), "panel": panel, "age": age, "age_band": "60대" if age == 65 else "30대",
            "province": "부산", "region": "동남권", "sex": "여자", "stance": stance,
            "probabilities": probabilities, "source": "decision_model",
            "reason": "이동에 필요한 지원 절차를 현장에서 확인하고 싶습니다.",
            **({"control": control, "reversed": reverse or probabilities} if control else {})}


@pytest.mark.parametrize("n,hidden,warning", [(0, True, "극소"), (4, True, "극소"), (5, False, "소집단"), (29, False, "소집단"), (30, False, "여유"), (99, False, "여유"), (100, False, None)])
def test_small_group_tiers_and_slices(n, hidden, warning):
    result = numbers.build([row(i) for i in range(n)])
    dist = result["overall"]
    sliced = numbers.slice_results(result)
    for value in (dist, sliced):
        assert value["n"] == n and value["rates_hidden"] is hidden
        assert (value["rates"] is None) is hidden
        assert warning in value["warning"] if warning else value["warning"] is None
    assert sliced["cost_usd"] == sliced["model_calls"] == 0
    assert not sliced["highlight"]


def test_panel_separation_dedup_filters_and_reason_samples():
    rows = [row(i) for i in range(6)] + [row(7, panel="affected", stance="oppose")]
    result = numbers.build(rows + [rows[0]])
    assert result["overall"]["n"] == 6
    assert result["overall"]["affected"]["n"] == 1
    assert result["overall"]["rates"]["oppose"] == 0
    sliced = numbers.slice_results(result, {"age_min": 60, "age_max": 69, "region": "동남권", "province": "부산", "sex": "여자", "stance": "support"})
    assert sliced["n"] == 6 and len(sliced["reasons"]) == 3
    aff = numbers.slice_results(result, {"panel": "affected", "stance": "oppose"})
    assert aff["n"] == 1 and aff["rates"] is None
    assert numbers.slice_results(result, {"province": "서울"})["n"] == 0


def test_variability_and_comparison_guard():
    p = {"support": .9, "oppose": .05, "unknown": .05}
    rows = [row(i, control=p, reverse=p) for i in range(120)]
    result = numbers.build(rows)
    assert result["overall"]["variability"]["width_pp"] == pytest.approx(10)
    assert result["overall"]["variability"]["warning_code"] == "UNSTABLE_PP"
    assert result["highlights"] == []
    assert numbers.slice_results(result)["variability"]["unstable"]


def test_highlights_require_measured_stable_difference_and_100_members():
    rows = []
    for i in range(240):
        r = row(i, age=65 if i < 120 else 35, stance="support" if i < 120 else "oppose")
        r.update(control=r["probabilities"], reversed=r["probabilities"])
        rows.append(r)
    result = numbers.build(rows)
    assert len(result["highlights"]) == 2
    assert all(h["outreach"]["venues"] and h["comparison_threshold_pp"] > 6 for h in result["highlights"])


@pytest.mark.parametrize("filters", [{"sex": []}, {"age_min": True}, {"age_min": 70, "age_max": 30}, {"stance": "maybe"}, {"panel": "all"}, {"secret": "x"}])
def test_invalid_filters_fail(filters):
    with pytest.raises(ValueError):
        numbers.slice_results(numbers.build([]), filters)


def test_default_decision_stage_is_3000_with_200_reasons_and_zero_cost_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")  # Explicit provider must not escape trial guard.
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(tmp_path / "absent.gz"))
    monkeypatch.setenv("PP_PERSONA_SOURCE", "bundle")
    monkeypatch.setattr(jev.net, "post", lambda *a, **k: pytest.fail("paid call forbidden"))
    estimate = service.estimate(POLICY)
    assert estimate["stages"]["distribution"]["n"] == 3000
    assert estimate["stages"]["reasons"]["n"] == 200
    result = service.run_policy(POLICY, sample=12)
    assert result["schema"] == "pp.run/4"
    assert result["overall"]["n"] == 3000
    assert result["overall"]["reason_sample_n"] == 12
    assert result["overall"]["variability"]["available"]
    assert result["budget"]["cost_usd"] == 0
    assert result["slice_data"]["reason_rows"]


def test_no_decision_key_falls_back_without_pretending_3000(fake_models, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    result = service.run_policy(POLICY, sample=12, credentials=service.Credentials("fake"))
    assert result["overall"]["decision"]["fallback"]
    assert result["overall"]["n"] <= 12
    assert not result["overall"]["variability"]["available"]
    assert any("소표본" in warning for warning in result["warnings"])
    assert result["estimate"]["stages"]["distribution"]["estimated_cost_usd"]["high"] == 0


def test_explicit_mock_judgment_stays_mock_with_request_key(fake_models, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setattr(jev.net, "post", lambda *a, **k: pytest.fail("paid call forbidden"))
    result = service.run_policy(POLICY, sample=6, decision_sample=6, credentials=service.Credentials("fake", "fake-jev"))
    assert result["overall"]["decision"]["model"] == "mock"
    assert result["overall"]["decision"]["n"] == 6
    assert result["estimate"]["stages"]["distribution"]["estimated_cost_usd"]["high"] == 0


@pytest.mark.parametrize("value", [True, 0, 5001, 2.5, "3000"])
def test_decision_sample_validation(value):
    with pytest.raises(service.RequestError):
        service.estimate(POLICY, decision_sample=value)


def test_estimate_splits_costs_with_jev_and_upstage(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "api")
    monkeypatch.setenv("PP_JEV_PROVIDER", "upstage")
    monkeypatch.setenv("UPSTAGE_API_KEY", "fake-key")
    result = service.estimate(POLICY, decision_sample=5000)
    stages = result["stages"]
    assert stages["distribution"]["n"] == 5000
    assert stages["distribution"]["estimated_cost_usd"]["high"] > 0
    assert result["estimated_cost_usd"]["high"] == pytest.approx(sum(s["estimated_cost_usd"]["high"] for s in stages.values()), abs=.0001)


def exact_baseline():
    prediction = predict([{"question_id": "q1", "group": "all", "definition_id": "exact-v1", "year": 2024,
        "released_at": "2024-12-20", "fieldwork_end": "2024-10-01", "source_url": "https://example.org/public",
        "options": ["찬성", "반대", "모름"], "probabilities": [.5, .3, .2]}],
        question_id="q1", group="all", definition_id="exact-v1", target_year=2026, as_of="2025-12-31")
    prediction["definition"] = {**{k: prediction[k] for k in ("question_id", "definition_id", "group", "options")},
        "policy_text": POLICY, "population": "대한민국 19세 이상", "group_boundaries": "전체",
        "stance_keys": ["support", "oppose", "unknown"], "confirmed": True}
    return prediction


def test_exact_baseline_is_preserved_through_run_and_plan(fake_models, monkeypatch):
    baseline = exact_baseline()
    result = service.run_policy(POLICY, sample=12, baseline=baseline)
    assert result["baseline"]["available"] and result["baseline"]["rates"]["support"] == .5
    assert result["baseline"]["model_calls"] == 0
    jobs = Jobs()
    try:
        quote = jobs.estimate(POLICY, baseline=baseline)
        assert quote["baseline"]["available"]
        assert quote["input_hash"] != jobs.estimate(POLICY)["input_hash"]
    finally:
        jobs.close()


@pytest.mark.parametrize("field,value", [("policy_text", "비슷한 문안"), ("population", "대한민국 전체"), ("confirmed", False), ("options", ["찬성", "모름", "반대"]), ("definition_id", "different")])
def test_baseline_rejects_near_matches(field, value):
    baseline = exact_baseline()
    baseline["definition"][field] = value
    with pytest.raises(service.RequestError):
        service.estimate(POLICY, baseline=baseline)


def test_decision_budget_stop_has_zero_paid_transport(monkeypatch, tmp_path):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_PERSONA_SOURCE", "bundle")
    monkeypatch.setenv("PP_PANEL_BUNDLE", str(tmp_path / "missing.gz"))
    monkeypatch.setattr(jev.net, "post", lambda *a, **k: pytest.fail("paid transport forbidden"))
    with pytest.raises(budget.BudgetExceeded) as stopped:
        service.run_policy(POLICY, sample=12, limits={"max_calls": 3})
    assert stopped.value.budget_snapshot["calls"] == 3


@pytest.mark.parametrize("example", archived_examples.EXAMPLES)
def test_archived_numbers_preserve_actual_mass_without_inventing_groups(example):
    result = archived_examples.load(example)
    assert result["schema"] == "pp.run/4"
    overall = result["overall"]
    mass = overall["original_mass"]
    assert overall["rates"]["support"] == mass[3] + mass[4]
    assert not overall["variability"]["available"]
    assert all(group["rates"] is None for group in result["by_group"]["age_band"] if group["panel"] == "representative")
    assert any(group["panel"] == "affected" for group in result["by_group"]["age_band"])
    sliced = numbers.slice_results(result, {"age_min": 60})
    assert sliced["source_scope"] == "archived_reason_sample" and sliced["cost_usd"] == 0
    if example == "subway-free-ride":
        assert overall["n"] == 5000
        assert overall["rates"]["support"] == pytest.approx(.4693)


def test_api_and_cli_slices_are_free(monkeypatch, tmp_path, capsys):
    result = numbers.build([row(i) for i in range(6)])
    with TestClient(api.create_app()) as client:
        response = client.post("/slice-results", json={"result": result, "filters": {"age_min": 60}})
        assert response.status_code == 200 and response.json()["n"] == 6
        assert client.post("/slice-results", json={"result": result, "filters": {"panel": "all"}}).status_code == 400
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(result))
    assert cli.main(["slice-results", str(path), "--filters", '{"age_min":60}']) == 0
    assert json.loads(capsys.readouterr().out)["cost_usd"] == 0


def test_mcp_slice_results_and_plan_settings(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    jobs = Jobs()
    try:
        server = mcp.create_server(jobs)
        async def scenario():
            result = await server.call_tool("slice_results", {"result": numbers.build([row(i) for i in range(6)])})
            assert not result.isError and result.structuredContent["model_calls"] == 0
            bad = await server.call_tool("estimate", {"policy_text": POLICY, "decision_sample": True})
            assert bad.isError
        asyncio.run(scenario())
        quote = jobs.estimate(POLICY, decision_sample=123)
        with pytest.raises(service.RequestError):
            jobs.start_planned(plan_id=quote["plan_id"], decision_sample=124)
        assert jobs._plans.items[quote["plan_id"]]["settings"]["decision_sample"] == 123
    finally:
        jobs.close()
