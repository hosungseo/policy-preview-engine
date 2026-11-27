"""Exercise the actual pp.run/4 aggregates through the numbers-first presentation."""
from copy import deepcopy

import pytest

from pp import archived_examples, numbers, numbers_copy as nc, summary_card


def native_result():
    rows = []
    for i in range(300):
        probabilities = {"support": .1, "oppose": .8, "unknown": .1} if i < 100 else {"support": .9, "oppose": .05, "unknown": .05}
        rows.append({"id": str(i), "panel": "representative", "age": 65 if i < 100 else 35,
                     "age_band": "60대" if i < 100 else "30대", "region": "수도권", "province": "서울",
                     "sex": "여자", "probabilities": probabilities, "control": probabilities,
                     "reversed": probabilities, "source": "decision_model", "stance": max(probabilities, key=probabilities.get)})
    affected = {**rows[0], "id": "affected", "panel": "affected"}
    return {"schema": "pp.run/4", **numbers.build(rows + [affected], population=1000000,
             decision={"model": "Jev", "fallback": False}, reason_n=20)}


def test_native_contract_maps_rates_panels_and_highlight_venues_without_mutating():
    result = native_result()
    original = deepcopy(result)
    view = nc.view(result)
    assert result == original
    assert view["n"] == 300 and view["pool"] == 1000000 and view["model"] == "Jev"
    assert view["favor"] == pytest.approx(result["overall"]["rates"]["support"])
    assert view["swing_pp"] == 3 and view["reasons_n"] == 20
    assert view["affected"]["n"] == 1 and len(view["rows"]) == 4
    assert {r["n"] for r in view["rows"]} == {100, 200, 300}
    assert view["highlights"] and all(h["venue"] for h in view["highlights"])
    card = summary_card.build(result, "native")
    assert card["numbers"]["highlights"] and "찾아갈 곳 후보:" in card["text"]
    assert "distribution_selection" not in card["overall"]
    assert len(card["text"]) <= summary_card.MAX_CHARS


def test_native_fallback_and_control_instability_preserve_limits():
    result = native_result()
    result["overall"]["decision"] = {"model": "unavailable-judge", "fallback": True}
    result["conditions"] = {"model": "Claude"}
    view = nc.view(result)
    assert view["fallback"] and view["model"] == "Claude"
    result["overall"]["variability"].update(control_pp=8.2, width_pp=8.2, unstable=True)
    view = nc.view(result)
    assert view["unstable"] and not view["highlights"]
    assert not any(r["exceeds"] for r in view["rows"])
    assert nc.UNSTABLE in nc.top_lines(view)


def test_native_slice_uses_its_own_variability_and_safe_reason_text():
    result = native_result()
    result["slice_data"]["reason_rows"] = [{**result["slice_data"]["rows"][0], "reason": "안내가 걱정입니다."}]
    result["overall"]["variability"]["width_pp"] = 6.4
    sliced = numbers.slice_results(result, {"age_band": "60대"})
    text = nc.slice_text(sliced, nc.view(result))
    assert "흔들림 3.0%p" in text and "흔들림 6.4%p" not in text
    assert "안내가 걱정입니다." in text and "문장 모델이라 한쪽으로 쏠릴 수 있음" in text
    assert nc.violations(text) == []
    sliced = numbers.slice_results(result, {"age_min": 99})
    assert "0명" in nc.slice_text(sliced) and "%" not in nc.slice_text(sliced)


@pytest.mark.parametrize("example", archived_examples.EXAMPLES)
def test_packaged_archive_renders_real_numbers_and_no_invented_components(example):
    result = archived_examples.load(example)
    card = summary_card.build(result, "archive")
    view = card["numbers"]
    assert view["n"] == 5000 and view["model"] == "Jev" and view["swing_pp"] is None
    assert not view["highlights"] and "▲" not in card["text"]
    assert all(r["oppose"] is None and r["unsure"] is None for r in view["rows"])
    assert all(r["favor"] is not None and r["reserve"] is not None for r in view["rows"])
    assert nc.violations(card["text"]) == []
    if example == "subway-free-ride":
        assert view["favor"] == pytest.approx(.4693)
        assert "| 60대 | 893명 | 39% | 61% | -8%p |" in card["text"]
    for c in card["cards"]:
        assert c["questions"][0] in card["text"]


def test_native_tiny_groups_keep_headcounts_and_hide_percentages():
    result = native_result()
    tiny = result["slice_data"]["rows"][:4]
    result = numbers.build(tiny, population=1000000, decision={"model": "Jev"})
    view = nc.view(result)
    assert view is not None and view["n"] == 4
    distribution = next(line for line in nc.top_lines(view) if line.startswith("대표 패널"))
    assert "%" not in distribution.split(" (흔들림")[0] and "해석 불가" in distribution
    assert "4명" in "\n".join(nc.table_lines(view))


def test_native_baseline_keeps_source_year_and_availability():
    result = native_result()
    result["baseline"] = {"available": True, "options": ["찬성", "반대", "모름"],
                          "probabilities": [.54, .30, .16], "method": "last",
                          "history_sources": [{"year": 2024}], "source_name": "통계청 사회조사"}
    line = nc.baseline_line(nc.view(result)["baseline"])
    assert "2024 통계청 사회조사" in line and "찬성 54%" in line and "직전값" in line
    result["baseline"]["available"] = False
    assert nc.view(result)["baseline"] is None
