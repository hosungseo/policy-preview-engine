"""Numbers-first wording: phrase list, forbidden expressions, small-group tiers, panels and the card layout."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from pp import archived_examples, mcp_setup, numbers_copy as nc, public_rules, safety_gate, summary_card
from pp import trend_baseline

ROOT = Path(__file__).resolve().parents[2]


def archive_numbers(key: str) -> dict:
    """Engine-shaped fields from an archived run's judge-model (Jev) aggregate, as integration will add them."""
    data = json.loads((ROOT / "web/public/runs" / f"{key}.json").read_text())
    jev, panel = data["analysis"]["jev"], data["panel"]
    mass = jev["overall"]["mass"]  # five-point scale, strongly against .. strongly for
    return {"overall": {"n": jev["n"], "model": "Jev", "model_kind": "judge", "favor": mass[3] + mass[4],
                        "oppose": mass[0] + mass[1], "unsure": mass[2],
                        "reasons_n": panel["representative"]["n"] + panel["affected"]["n"],
                        "reasons_by_panel": {"representative": panel["representative"]["n"],
                                             "affected": panel["affected"]["n"]}},
            "by_group": {axis: [{"group": g["group"], "n": g["n"], "favor": 1 - g["reserve"], "reserve": g["reserve"]}
                                for g in jev["by_group"][axis]] for axis in nc.TABLE_AXES}}


def row(group, n, favor, oppose, **extra):
    return {"group": group, "n": n, "favor": favor, "oppose": oppose, "unsure": round(1 - favor - oppose, 4), **extra}


def engine_like(result=None, **overall):
    """A run carrying every assumed engine field: wobble measured, all four small-group tiers, both panels."""
    result = deepcopy(result) if result is not None else archived_examples.load("subway-free-ride")
    result["overall"] = {"n": 5000, "model": "Jev", "model_kind": "judge", "favor": .469, "oppose": .172,
                         "unsure": .359, "contrast_pp": 2.1, "order_pp": 3.8, "reasons_n": 400,
                         "reasons_by_panel": {"representative": 300, "affected": 100},
                         "affected": {"n": 100, "label": "65~69세 도시철도 이용자", "favor": .29, "oppose": .41,
                                      "unsure": .30}, **overall}
    result["by_group"] = {
        "age_band": [row("19–29세", 728, .45, .15), row("30대", 748, .49, .14), row("60대", 893, .39, .27),
                     row("70세 이상", 759, .57, .12)],
        "region": [row("동남권", 146, .38, .25), row("제주", 65, .58, .1), row("세종", 18, .5, .2), row("울릉", 4, .25, .5)],
        "sex": [row("남자", 2478, .47, .17), row("여자", 2522, .47, .17)]}
    result["highlights"] = [
        {"label": "60대 · 동남권", "n": 146, "measure": "reserve", "share": .62, "diff_pp": 9.0, "groups": ["60대"]},
        {"label": "70세 이상", "n": 759, "measure": "favor", "share": .57, "diff_pp": 10.1, "venue": "노인복지관"},
        {"label": "세종", "n": 18, "measure": "favor", "share": .5, "diff_pp": 3.1}]
    result["baseline"] = None
    result["slice_results"] = [{"filters": {"age_band": "60대"}, "panel": "representative",
                                "n": 893, "favor": .39, "oppose": .27, "unsure": .34}]
    return result


def baseline():
    rows = [dict(question_id="q", group="전체", definition_id="q-v1", year=2024, fieldwork_end="2024-05-30",
                 released_at="2024-11-20", source_url="https://kosis.kr/example", options=["찬성", "반대", "모름"],
                 probabilities=[.54, .30, .16])]
    return {**trend_baseline.predict(rows, question_id="q", group="전체", definition_id="q-v1", target_year=2026,
                                     as_of="2025-12-31"), "source_name": "통계청 사회조사"}


def emitted() -> list[str]:
    """Every phrase this module can produce, across modes, tiers, panels and baselines."""
    texts = []
    variants = [engine_like(), engine_like(order_pp=8.2), engine_like(model_kind="text", model="Claude", n=300),
                engine_like(contrast_pp=None, order_pp=None, swing_pp=None),
                {**engine_like(), "mode": "mock"}, {**engine_like(), "baseline": baseline()}]
    variants += [{**archived_examples.load(k), **archive_numbers(k)} for k in archived_examples.EXAMPLES]
    for result in variants:
        numbers = nc.view(result)
        texts += nc.top_lines(numbers) + nc.table_lines(numbers) + [nc.affected_line(numbers) or ""]
        texts += [nc.basis_line(h) for h in numbers["highlights"]] + [nc.candidate_line(h, None) for h in numbers["highlights"]]
        for n in (3, 12, 64, 893):
            for panel in nc.PANELS:
                texts.append(nc.slice_text({"filters": {"age_band": "60대", "education_level": "대학원"}, "panel": panel,
                                            "n": n, "favor": .4, "oppose": .3, "unsure": .3,
                                            "reasons": ["요금이 오르면 외출을 줄일 것 같습니다."]}, numbers))
    return texts


def test_thresholds_match_the_service_survey():
    from ppservice.survey import aggregate
    assert (nc.FLOOR_PP, nc.UNSTABLE_PP, nc.MIN_GROUP) == (aggregate.FLOOR_PP, aggregate.UNSTABLE_PP, aggregate.MIN_GROUP)


def test_number_formats_keep_minorities_and_add_up():
    assert [nc.pct(v) for v in (0, .0004, .004, .469, .995, .9996, 1)] == [
        "0%", "<0.1%", "0.4%", "47%", "99.5%", ">99.9%", "100%"]
    assert nc.shares_text(.469, .172, .359) == [("찬성 쪽", "47%"), ("반대 쪽", "17%"), ("모름", "36%")]
    assert sum(int(v[:-1]) for _, v in nc.shares_text(.335, .335, .33)) == 100
    assert nc.shares_text(.39, reserve=.61) == [("찬성 쪽", "39%"), ("반대·유보", "61%")]
    assert (nc.signed(-7.8), nc.signed(.4), nc.signed(9)) == ("-8%p", "0%p", "+9%p")
    assert (nc.pool(1_000_000), nc.people(5000), nc.pp(3.8)) == ("100만 명", "5,000명", "3.8%p")
    assert sum(c for _, c in nc.counts_text(4, .25, .5, .25, three=True)) == 4


BAD = [
    ("국민의 47%가 찬성", "real_subject"),
    ("도시철도 무임승차 연령 상향 여론조사 결과 — 5,000명 응답, 찬성 47% · 반대 38% · 모름 15% "
     "(표본오차 ±1.4%p). 국민 다수가 찬성 쪽으로 나타났다.", "survey"),
    ("도시철도 무임승차 연령 상향 여론조사 결과 — 5,000명 응답 (표본오차 ±1.4%p).", "sampling_error"),
    ("국민 다수가 찬성 쪽으로 나타났다.", "definite"),
    ("60대 동남권 주민은 62%가 반대하므로 정책 수용성이 낮다.", "real_subject"),
    ("(대표 5,000명과 영향권 100명을 합쳐 집계)", "panel_mix"),
    ("전체 5,400명(대표 5,000 + 영향권 400) 찬성 48%", "panel_mix"),
    ("필터: 70대 이상 · 제주 · 자영업 → 반대 75%! (4명 중 3명).", "tiny_percent"),
    ("Pew 연구 기준 오차 ±12%p.", "borrowed_error"),
    ("작년 비슷한 설문(찬성 60%)보다 크게 떨어졌다.", "no_subject"),
    ("60대 대다수가 반대한다", "generalize"),
    ("시민들은 찬성한다", "generalize"),
    ("95% 신뢰수준 ±3%p", "sampling_error"),
    ("찬성률 1위는 30대", "rate_rank"),
    ("민심은 반대 쪽이다", "survey"),
    ("응답자의 62%가 반대", "survey"),
    ("60대의 62%가 반대·유보", "real_subject"),
    ("찬성 47% · 반대 17%", "no_subject"),
    ("이 문안은 수급 대상 확정 기준을 바꾼다", "rate_rank"),
]

GOOD = [
    "합성 인물 3,000명 중 찬성 쪽 47%(±3%p)",
    # Good examples of the numbers guideline, verbatim apart from markdown.
    "합성 인물 모의 응답(실제 사람 0명)입니다. 여론조사가 아니며, 먼저 찾아갈 집단과 질문을 고르는 참고값입니다. (보관 결과 · 열람 0원)\n"
    "규모: 100만 명 합성 풀 중 인구 비율 추출 5,000명 추정 (판단 모델: Jev · 이유 수집: 문장 모델 400명 별도)\n"
    "대표 패널 모의 분포: 찬성 쪽 47% · 반대 쪽 38% · 모름 15% (흔들림 폭 ±3.8%p · 대조/순서 기준, '모름' 비율은 실제보다 낮게 추정될 수 있음)\n"
    "명단 밖 확인 필요: 19세 미만, 외국인 주민, 운영기관·노인단체",
    "[대표 패널 집단표 · 흔들림 폭(±3.8%p) 초과 집단 강조]\n"
    "60대 · 동남권 (146명 중 반대·유보 추정 62%, 전체 대비 +9%p) → 우선 방문 후보: 경로당·노인복지관 현장 간담회로 실제 이유 확인\n"
    "[별도 카드 · 영향권 패널(비대표)] 도시철도 무임 이용 예상 구간 100명 중 반대·유보 추정 71% (전체 비율에 합산하지 않음)",
    "필터(대표 패널): 70대 이상 · 제주 · 자영업 → 4명 중 반대·유보 3명 (5명 미만: 비율 비표시 · 표본 극소로 해석 불가, 찾아갈 곳 단독 근거 제외)\n"
    "과거 공개 기준선: 동일 문항 공개 집계 없음 (유사 설문·해외 오차 수치는 비교하지 않음)\n"
    "과거 공개 기준선(참고): 찬성 54% [2024 통계청 사회조사 · 직전값 · 과거 추세이며 정답 아님]",
    public_rules.NOTICE, mcp_setup.TRIAL_NOTICE, archived_examples.NOTICE,
]


@pytest.mark.parametrize("text,rule", BAD)
def test_forbidden_expressions_are_caught(text, rule):
    assert rule in {name for name, _ in nc.violations(text)}, nc.violations(text)


@pytest.mark.parametrize("text", GOOD)
def test_good_examples_pass(text):
    assert nc.violations(text) == []


def test_every_forbidden_rule_has_a_reason_and_replacement():
    assert {rule.name for rule in nc.FORBIDDEN} | {"no_subject"} == {rule for _, rule in BAD}
    assert all(rule.why.endswith(".") and rule.instead for rule in nc.FORBIDDEN)


def test_every_emitted_phrase_is_clean_and_passes_the_safety_gate(monkeypatch):
    texts = emitted()
    assert all(nc.violations(t) == [] for t in texts), [(t, nc.violations(t)) for t in texts if nc.violations(t)]
    monkeypatch.setenv("PP_SAFETY_GATE", "report")
    assert safety_gate.apply({"text": "\n".join(texts)})["safety_gate"]["findings"] == []


def test_top_block_puts_the_banner_before_any_number():
    lines = nc.top_lines(nc.view({**engine_like(), "mode": "archived"}))
    first_number = next(i for i, line in enumerate(lines) if "%" in line)
    assert lines[:3] == [nc.HEAD, nc.BANNER, nc.TAILS["archived"]] and first_number > 1
    assert ("규모: 합성 인물 풀 100만 명 중 인구 비율(시도·연령·성별)대로 뽑은 5,000명 추정"
            "(판단 모델: Jev · 이유 수집: 문장 모델 400명 별도, 대표 300·영향권 100)") in lines
    assert ("대표 패널 모의 분포: 찬성 쪽 47% · 반대 쪽 17% · 모름 36% "
            "(흔들림 폭 ±3.8%p: 대조 문장 2.1%p·선택지 순서 3.8%p 중 큰 값, 최소 3.0%p)") in lines
    assert nc.UNSURE_NOTE in lines and nc.BASELINE_NONE in lines and lines[-1] == nc.OUTSIDE
    assert nc.TAILS["archived"] not in nc.top_lines(nc.view({**engine_like(), "mode": "archived"}), tail=False)


def test_wobble_floor_unknown_wobble_and_unstable_order():
    assert nc.view(engine_like(contrast_pp=1.0, order_pp=2.0))["swing_pp"] == nc.FLOOR_PP
    unknown = nc.view(engine_like(contrast_pp=None, order_pp=None))
    assert unknown["swing_pp"] is None and unknown["highlights"] == []
    assert any(line.endswith(nc.SWING_UNKNOWN) for line in nc.top_lines(unknown))
    assert not any(r["exceeds"] for r in unknown["rows"])
    assert nc.table_lines(unknown)[0] == nc.TABLE_HEAD_NONE and "▲" not in "\n".join(nc.table_lines(unknown))
    unstable = nc.view(engine_like(order_pp=8.2))
    lines = nc.top_lines(unstable)
    assert lines[lines.index(next(l for l in lines if l.startswith("대표 패널 모의 분포"))) + 1] == nc.UNSTABLE
    assert unstable["highlights"] == []  # unstable numbers never point to a place to visit


def test_group_table_applies_the_four_small_group_tiers():
    numbers = nc.view(engine_like())
    table = nc.table_lines(numbers)
    cells = {line.split(" | ")[0].strip("| "): line for line in table if line.startswith("| ") and "명" in line}
    assert cells["울릉"] == "| 울릉 | 4명 | 1명 | 2명 | 1명 | 해석 불가(5명 미만) |"  # no percent under 5
    assert "명·" in cells["세종"] and nc.SMALL_CELL in cells["세종"] and "▲" not in cells["세종"]
    assert cells["제주"].endswith(nc.THIN_CELL + " |") and "▲" not in cells["제주"]  # 30–99: note, no mark
    assert cells["동남권"].endswith("▲ |") and cells["70세 이상"].endswith("▲ |")  # 100+ beyond the wobble
    assert not cells["30대"].endswith("▲ |") and table[2] == "| " + " | ".join(nc.TABLE_COLUMNS) + " |"
    assert [h["label"] for h in numbers["highlights"]] == ["60대 · 동남권", "70세 이상"]  # 18 people: dropped


def test_slices_follow_tiers_and_never_mix_panels():
    numbers = nc.view(engine_like())
    tiny = nc.slice_text({"filters": {"age_band": "70세 이상", "province": "제주"}, "n": 4, "favor": .25, "reserve": .75}, numbers)
    assert tiny.startswith("[대표 패널] 70세 이상 · 제주: 합성 인물 4명 중 찬성 쪽 1명 · 반대·유보 3명")
    assert "%" not in tiny and nc.TINY_NOTE in tiny
    small = nc.slice_text({"filters": {"sex": "여자"}, "n": 18, "favor": .39, "reserve": .61}, numbers)
    assert "18명 중 찬성 쪽 7명(39%) · 반대·유보 11명(61%)" in small and nc.SMALL_NOTE in small
    full = nc.slice_text({"filters": {"age_band": "60대"}, "n": 893, "favor": .39, "oppose": .27, "unsure": .34}, numbers)
    assert full == ("[대표 패널] 60대: 합성 인물 893명 중 찬성 쪽 39% · 반대 쪽 27% · 모름 34% "
                    "(전체 대비 찬성 쪽 -8%p) (흔들림 폭 ±3.8%p)")
    affected = nc.slice_text({"panel": "affected", "n": 100, "favor": .29, "oppose": .41, "unsure": .30}, numbers)
    assert affected.startswith("[영향권 패널 · 비대표] 전체: 합성 인물 100명") and "전체 대비" not in affected
    with pytest.raises(ValueError):
        nc.slice_text({"panel": "all", "n": 5100, "favor": .47}, numbers)
    warnings = []
    reasons = nc.slice_text({"filters": {"education_level": "대학원"}, "n": 247, "favor": .5, "reserve": .5,
                             "reasons": ["대부분 찬성할 것 같아요", "요금보다 안내가 걱정입니다"], "reasons_n": 300},
                            numbers, warnings)
    assert nc.INFLATE_NOTE in reasons and "문장 모델 표본 300명" in reasons and "대부분" not in reasons
    assert "요금보다 안내가 걱정입니다" in reasons and warnings  # model prose still meets the prose rules


def test_fallback_mock_and_baseline_lines():
    fallback = nc.top_lines(nc.view(engine_like(model_kind="text", model="Claude", n=300)))
    assert nc.TAILS["fallback"].replace("{n}", "300명") in fallback
    assert any(line.startswith("규모:") and "300명(문장 모델 Claude 소표본)" in line for line in fallback)
    assert nc.TAILS["mock"] in nc.top_lines(nc.view({**engine_like(), "mode": "mock"}))
    line = nc.baseline_line(baseline())
    assert line.startswith("과거 공개 기준선(참고): 찬성 54% · 반대 30% · 모름 16% [2024 통계청 사회조사 · 직전값 · 모델 호출 0회]")
    assert line.endswith("현재 여론이나 합성 응답의 정답이 아닙니다.")
    assert nc.view({"overall": {"n": 0, "favor": .5}}) is None and nc.view({}) is None


def text_index(text, needle):
    assert needle in text, needle
    return text.index(needle)


def test_card_order_is_numbers_table_places_then_people_outside():
    result = engine_like()
    result["who_to_ask"] = result["who_to_ask"][:1]  # leave room for every section, re-aggregations included
    original = deepcopy(result)
    card = summary_card.build(result, "run")
    text = card["text"]
    assert result == original and len(text) <= summary_card.MAX_CHARS
    order = [public_rules.NOTICE, nc.BANNER, "대표 패널 모의 분포:", "| 집단 |", nc.AFFECTED.split(":")[0],
             nc.SLICE_HEAD, summary_card.MORE_NUMBERS, "찾아갈 곳 · 먼저 물을 질문", "명단 밖 사람 · 빠진 관점"]
    assert [text_index(text, n) for n in order] == sorted(text_index(text, n) for n in order)
    assert text_index(text, nc.BANNER) < text_index(text, "%")
    assert nc.TAILS["archived"] not in text  # the archive notice already opens the card
    assert card["numbers"]["schema"] == "pp.numbers/1"
    numbers_part = text[text_index(text, nc.HEAD):text_index(text, "현장에서 확인할 질문 초안")]
    assert nc.violations(numbers_part) == []


def test_numbers_lead_to_places_to_visit():
    card = summary_card.build(engine_like(), "run")
    first = card["cards"][0]  # the first card lists 60대, the highlight's group
    assert first["numbers_basis"] == ("숫자 근거: 60대 · 동남권 합성 인물 146명 중 반대·유보 추정 62%"
                                      "(전체 대비 +9%p, 흔들림 폭 초과)")
    assert "• " + " · ".join(first["groups"]) + "\n  " + first["numbers_basis"] in card["text"]
    assert nc.CANDIDATES_HEAD in card["text"]
    assert "• 70세 이상: 합성 인물 759명 중 찬성 쪽 추정 57%(전체 대비 +10%p, 흔들림 폭 초과) → 찾아갈 곳 후보: 노인복지관" in card["text"]
    assert "세종:" not in card["text"]  # 18 people never become visit evidence


@pytest.mark.parametrize("key", archived_examples.EXAMPLES)
def test_archived_examples_with_real_judge_numbers_keep_every_card(key):
    result = {**archived_examples.load(key), **archive_numbers(key)}
    card = summary_card.build(result, "archive")
    text = card["text"]
    assert len(text) <= summary_card.MAX_CHARS
    assert text.splitlines()[0] == public_rules.NOTICE and nc.BANNER in text and "5,000명 추정(판단 모델: Jev" in text
    assert "대표 패널 모의 분포: 찬성 쪽 " in text and nc.SWING_UNKNOWN in text  # archives have no wobble record
    assert all("| " + r["group"] + " | " in text for r in card["numbers"]["rows"] if r["axis"] == "age_band")
    for c in card["cards"]:
        assert "먼저 물을 질문(편집 초안): " + c["questions"][0] in text
        assert all("보관 결과 인용: " + q in text for q in c.get("reaction_quotes", []))
        assert all(hint in text for hint in c["contact_hints"])
    assert "명단 밖 사람 · 빠진 관점" in text and text.rstrip().endswith('view="full")로 조회하세요.')
    assert nc.violations(text) == []


@pytest.mark.parametrize("mode", ["report", "block"])
def test_numbers_reach_the_assistant_through_mcp_unchanged(monkeypatch, mode):
    """try_example → MCP tool text: the card with numbers passes the optional output gate untouched."""
    import asyncio
    from pp import mcp
    from pp.jobs import Jobs
    load = archived_examples.load
    monkeypatch.setattr(archived_examples, "load", lambda key: {**load(key), **archive_numbers(key)})
    expected = summary_card.build(archived_examples.load("subway-free-ride"), "x")["text"]
    monkeypatch.setenv("PP_SAFETY_GATE", mode)
    jobs = Jobs()
    try:
        response = asyncio.run(mcp.create_server(jobs).call_tool("try_example", {"example": "subway-free-ride"}))
    finally:
        jobs.close()
    assert not response.isError
    text = response.content[0].text
    assert text == expected and nc.BANNER in text and "| 60대 | 893명 | 39% | 61% | -8%p |" in text
    assert response.structuredContent["safety_gate"]["findings"] == []


def test_numbers_stay_bounded_with_long_prose_and_many_slices():
    result = engine_like()
    result["who_to_ask"] *= 5
    for r in result["who_to_ask"]:
        r["questions"] = ["질문 문장입니다. " * 300] * 4
    result["slice_results"] *= 6
    card = summary_card.build(result, "run")
    assert len(card["text"]) <= summary_card.MAX_CHARS and card["truncated"]
    for needle in (nc.BANNER, "대표 패널 모의 분포:", "| 60대 |", nc.CANDIDATES_HEAD, summary_card.MORE_NUMBERS,
                   "명단 밖 사람 · 빠진 관점", "save_review"):
        assert needle in card["text"], needle
    assert nc.SLICE_HEAD not in card["text"]  # earlier re-aggregations give way first


def test_mock_numbers_keep_the_trial_line_first():
    result = {**engine_like(), "mode": "mock", "trial_notice": mcp_setup.TRIAL_NOTICE, "result_label": "체험"}
    text = summary_card.build(result, "run")["text"]
    assert text.splitlines()[0] == mcp_setup.TRIAL_NOTICE and public_rules.NOTICE in text
    assert text_index(text, nc.BANNER) < text_index(text, "%")


def test_results_without_numbers_show_no_numbers_block():
    card = summary_card.build(archived_examples.load("subway-free-ride"), "archive")
    assert "numbers" not in card and nc.BANNER not in card["text"] and summary_card.MORE_NUMBERS not in card["text"]


def test_example_result_summary_carries_numbers_once_the_archive_has_them(monkeypatch):
    from pp import mcp_copy
    load = archived_examples.load
    monkeypatch.setattr(archived_examples, "load", lambda key: {**load(key), **archive_numbers(key)})
    markdown = mcp_copy.result_summary_markdown()
    assert "## " + nc.HEAD in markdown and nc.BANNER in markdown and "| 60대 | 893명 |" in markdown
    assert markdown.index(nc.BANNER) < markdown.index("## 찾아갈 곳")
    assert nc.violations(markdown) == []


def test_docs_list_every_rule_and_the_assumed_fields():
    doc = (ROOT / "docs/numbers-copy.md").read_text()
    assert all(f"`{rule.name}`" in doc for rule in nc.FORBIDDEN) and "`no_subject`" in doc
    assert all(field in doc for field in ("overall", "by_group", "highlights", "baseline", "slice_results"))
    assert nc.BANNER in doc
