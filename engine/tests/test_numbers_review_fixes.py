"""Regressions from the numbers principle review and the first-use trial."""
import asyncio
from copy import deepcopy

import pytest

from pp import archived_examples, jev, mcp, numbers, numbers_copy as nc, safety_gate, summary_card
from pp.jobs import Jobs
from test_numbers import row
from test_numbers_integration import native_result


@pytest.mark.parametrize("example", archived_examples.EXAMPLES)
@pytest.mark.parametrize("filters,group", [({"age_band": "60대"}, "60대"), ({"age_min": 70}, "70세 이상"),
                                           ({"age_min": 60, "age_max": 69}, "60대")])
def test_archive_slice_uses_saved_group_and_only_quotes_reason_sample(example, filters, group):
    result = archived_examples.load(example)
    saved = next(g for g in result["by_group"]["age_band"] if g["panel"] == "representative" and g["group"] == group)
    original = deepcopy(result)
    sliced = numbers.slice_results(result, filters, reason_limit=10)
    assert result == original
    assert sliced["source_scope"] == "archived_group_table"
    assert (sliced["n"], sliced["favor"], sliced["reserve"]) == (saved["n"], saved["favor"], saved["reserve"])
    text = nc.slice_text(sliced, nc.view(result))
    assert nc.share_body(saved["n"], saved["favor"], reserve=saved["reserve"]) in text
    assert "70:" not in text
    assert "문장 모델이라 한쪽으로 쏠릴 수 있음" in text
    assert all("%" not in line for line in text.splitlines()[1:])  # voices carry no stance rates


@pytest.mark.parametrize("filters", [{}, {"age_band": "60대", "province": "서울"}, {"stance": "oppose"}, {"panel": "affected"}])
def test_archive_missing_cells_do_not_replace_jev_with_sentence_distribution(filters):
    result = archived_examples.load("subway-free-ride")
    sliced = numbers.slice_results(result, filters)
    if not filters:
        assert sliced["n"] == 5000 and sliced["rates"]["support"] == pytest.approx(.4693)
    else:
        assert sliced["n"] is None and sliced["rates"] is None and sliced["counts"] is None
        text = nc.slice_text(sliced, nc.view(result))
        assert "표에 있는 집단만" in text and "모의(0원) 실행이나 직접 실행" in text
        assert "%" not in text and "oppose" not in text


def test_raw_delta_rounded_once_and_same_at_float_boundary_in_table_and_slice():
    result = native_result()
    base = result["overall"]["rates"]["support"]
    for delta, expected in [(1.47, "+1%p"), (5.499999999999994, "+6%p"), (-5.499999999999994, "-6%p")]:
        result["by_group"]["age_band"][0]["rates"]["support"] = base + delta / 100
        item = {**result["by_group"]["age_band"][0], "filters": {"age_band": "60대"}}
        view = nc.view(result)
        assert expected in nc.slice_text(item, view)
        assert expected in "\n".join(nc.table_lines(view))


@pytest.mark.parametrize("n,panel", [(4, "representative"), (56, "representative"), (56, "affected")])
def test_real_contract_keeps_tiny_counts_and_thin_warning_without_variability(n, panel):
    result = numbers.build([row(i, panel=panel, stance="support" if i == 0 else "oppose") for i in range(n)])
    sliced = numbers.slice_results(result, {"panel": panel})
    text = nc.slice_text(sliced, nc.view(result))
    if n == 4:
        assert "찬성 쪽 1명 · 반대·유보 3명" in text and "%" not in text
        table = "\n".join(nc.table_lines(nc.view(result)))
        assert "1명 | 3명 | 0명" in table
    else:
        assert nc.THIN_NOTE in text


def test_stance_filter_is_voices_not_an_average_of_unfiltered_probabilities():
    result = native_result()
    result["slice_data"]["reason_rows"] = [
        {**result["slice_data"]["rows"][i], "reason": "이동 안내가 걱정입니다. " * 80} for i in range(11)]
    result["slice_data"]["reason_rows"][0]["reason"] = "규칙 검사로 문장을 제외함: 현장에서 확인할 질문이 필요합니다."
    sliced = numbers.slice_results(result, {"stance": "oppose"}, reason_limit=10)
    assert sliced["n"] == 100 and sliced["rates"] is None and sliced["counts"] is None
    assert len(sliced["reasons"]) == 10 and sliced["excluded_reason_n"] == 1
    text = nc.slice_text(sliced, nc.view(result))
    assert "반대한 합성 인물" in text and "oppose" not in text and "%" not in text
    assert all(f"{i}. " in text for i in range(1, 11))
    assert "규칙 검사로 문장을 제외함:" not in text
    assert len(nc.BANNER + "\n" + text) <= 3000


def test_selected_count_notice_and_affected_presentation_explain_different_measurement():
    result = archived_examples.load("subway-free-ride")
    affected = result["overall"]["affected"]
    assert affected["count_kind"] == "selected" and "문장 모델" in affected["count_notice"]
    assert "판단 모델의 확률 합계" not in affected["count_notice"]
    text = nc.affected_line(nc.view(result))
    assert "별도 측정" in text and "한쪽으로 쏠려" in text and "직접 비교할 수 없습니다" in text
    assert "%" not in text


@pytest.mark.parametrize("text", ["표본오차 ±1.4%p", "찬성률 1위", "60대의 62%", "4명 중 3명(75%)"])
def test_runtime_safety_gate_checks_numeric_forbidden_rules(text, monkeypatch):
    monkeypatch.setenv("PP_SAFETY_GATE", "block")
    gated = safety_gate.apply({"text": text})
    assert gated["safety_gate"]["blocked"] and text not in gated["text"]
    assert safety_gate.scan_text("통계적 표본오차가 아닙니다.") == []


def test_recovery_quote_screen_and_fallback_slice_are_readable(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_SAFETY_GATE", "block")
    jobs = Jobs()
    server = mcp.create_server(jobs)
    async def scenario():
        quote = await server.call_tool("estimate", {"policy_text": "교통비 지원 정책안"})
        text = quote.content[0].text
        assert "3,000명" in text and "200명" in text and "5,000명" in text and "{" not in text
        assert quote.structuredContent["recommended_sample"]["sample"] == 200
        wrong = await server.call_tool("slice_results", {"id": quote.structuredContent["plan_id"]})
        assert wrong.isError and wrong.structuredContent["code"] == "plan_id_as_run_id"
        assert "실행 번호를 넣으세요" in wrong.content[0].text
        missing = await server.call_tool("slice_results", {"id": "unknown-work-number"})
        assert missing.isError and missing.structuredContent["code"] == "run_not_found"
        bad = await server.call_tool("slice_results", {"result": native_result(), "filters": {"region": "서울"}})
        assert bad.isError and all(v in bad.content[0].text for v in ("수도권", "동남권", "province"))
        fallback = native_result()
        fallback["overall"]["decision"]["fallback"] = True
        reply = await server.call_tool("slice_results", {"result": fallback, "filters": {"age_band": "60대"}})
        assert nc.TAILS["fallback"].format(n="300명") in reply.content[0].text
        assert reply.structuredContent["safety_gate"]["findings"] == []
    try:
        asyncio.run(scenario())
    finally:
        jobs.close()


def test_mock_repeat_is_stable_and_reasons_are_not_censored(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    rows = numbers.judge("교통비 지원 정책안", [{"uuid": "x", "age": 65, "profile": "가상의 교통 이용자", "province": "서울"}])
    assert not numbers.variability(rows)["unstable"]
    from pp.mock import _react
    reason = _react("", "[정책]\n교통비 지원\n[/정책]")["reason"]
    from pp.public_rules import check_output
    assert check_output(reason, "", []) == reason


def test_archive_card_summary_is_hypothesis_and_has_actual_work_number():
    text = summary_card.build(archived_examples.load("subway-free-ride"), "actual-work-number")["text"]
    assert "보관 결과의 AI 요약, 위 숫자와 다를 수 있음" in text and "강하게 반발" not in text
    assert "actual-work-number" in text and "이 결과를 저장해 줘" in text
    assert "save_review(id)" not in text and "get_run(id" not in text
    assert "±" not in text and "AI가 5,000명의 반응을 추정(실제 조사 아님" in text
