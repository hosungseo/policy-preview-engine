import numpy as np

from pp import life_history as lh


def test_history_lines_state_changes_only():
    h = {"smoking": {"2023": True, "2024": False, "2025": False}, "income_q": {str(y): 3 for y in lh.INCOME_YEARS}}
    lines = lh.history_lines(h)
    assert lines == ["- 흡연 이력: 2023년까지 담배를 피우다 끊음"]
    h["income_q"]["2024"] = 4
    assert "- 개인 근로·사업소득 분위: 2023년 3분위 → 2024년 4분위" in lh.history_lines(h)
    low = {"income_q": {str(y): 1 for y in lh.INCOME_YEARS}}
    assert lh.history_lines(low) == ["- 2017~2024년 매년 개인 근로·사업소득 하위 20%"]


def test_ar_path_keeps_unit_variance_across_regimes():
    rng = np.random.default_rng(0)
    zs = np.array([lh._ar_path([0.7, 0.7, 0.2, 0.2], [0.5, 0.5, 0.9, 0.9], rng.standard_normal(), rng.standard_normal(4))
                   for _ in range(20000)])
    assert np.allclose(zs.std(axis=0), 1, atol=0.03)


def test_transition_rows_are_probabilities():
    from pp import life_context
    mob = life_context.tables()["history_income_mobility"]
    for year in ("2018", "2024"):
        P = lh.transition(mob, year, "여자", "40~64세")
        assert np.allclose(P.sum(axis=1), 1) and (P >= 0).all()
        assert P[0, 0] > 0.5 and P[4, 4] > 0.7


def test_age_at_uses_2025_panel_ages():
    p = {"age": 30}
    assert lh.age_at(p, 2024) == 29 and lh.age_group(lh.age_at(p, 2013)) is None


def test_new_history_lines():
    h = {"residence": {"2023": "경기", "2024": "서울", "2025": "서울"},
         "marital": {"2021": "미혼", "2022": "배우자있음", "2025": "배우자있음"},
         "employed": {"2024": True, "2025": False}}
    lines = lh.history_lines(h)
    assert "- 이사: 2024년 경기에서 서울(으)로 옮김" in lines
    assert "- 결혼: 2022년" in lines and "- 일: 2025년에 일을 그만둠" in lines


def test_band_rate_and_backward_binary_keep_final_state():
    assert lh.band_rate({"20": 0.1, "25": 0.2, "75+": 0.9}, 27) == 0.2
    assert lh.band_rate({"20": 0.1, "75+": 0.9}, 80) == 0.9
    rng = np.random.default_rng(1)
    for final in (True, False):
        path = lh.backward_binary(final, {2023: 0.3, 2024: 0.3, 2025: 0.3}, 0.9, 0.5, rng)
        assert path[2025] is final and set(path) == {2023, 2024, 2025}


def test_exit_bottom_moves_mass_up_one_quintile():
    P = np.eye(5) * 0.7 + 0.075
    Q = lh.exit_bottom(P, 0.05)
    assert np.isclose(Q[0, 0], P[0, 0] - 0.05) and np.isclose(Q[0, 1], P[0, 1] + 0.05)
    assert np.allclose(Q.sum(axis=1), P.sum(axis=1))


def test_backtest_block_states_only_differences():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import backtest_2019 as bt
    ref = {"province": "서울", "marital": "배우자있음", "working": True, "smoking": False, "income_q": 3}
    then = {"age": 40, "province": "경기", "marital": "배우자있음", "working": True, "smoking": False, "income_q": 1}
    text = bt.block(2019, ref, then, None)
    assert "2019년 현재 경기에 살고 있음" in text and "하위 20%" in text
    assert "혼인" not in text and "일:" not in text and "흡연" not in text
    since = {"province": "서울", "marital": "미혼", "working": False, "smoking": False, "income_q": 1}
    then23 = {**then, "age": 44, "marital": "배우자있음", "income_q": 2}
    text = bt.block(2023, ref, then23, since)
    assert "2019년 이후 서울에서 경기(으)로 옮김" in text and "미혼 → 2023년 배우자 있음" in text
    assert "일을 시작함" in text and "2019년 1분위 → 2023년 2분위" in text


def test_amount_layer_round_trip_and_categories():
    assert [lh.change_category(r) for r in (0.3, 0.7, 0.95, 1.0, 1.05, 1.3, 2.0)] == list(lh.CHANGE_CATS)
    levels = {"남자": {"40": {"mean": 500.0, "median": 420.0}}, "여자": {"40": {"mean": 350.0, "median": 280.0}}}
    people = [{"sex": "남자", "age": 45, "uuid": "a"}, {"sex": "여자", "age": 46, "uuid": "b"}] * 50
    cuts = lh.national_cuts(people, levels, 2025)
    assert cuts == sorted(cuts) and 0 < cuts[0] < cuts[3]
    for q in range(1, 6):
        a = lh.draw_amount("남자", 45, q, levels, cuts, 0.37)
        assert abs(lh.band_rank("남자", 45, q, levels, cuts, a) - 0.37) < 1e-6
        if q > 1:
            assert a >= cuts[q - 2] - 1e-6
        if q < 5:
            assert a <= cuts[q - 1] + 1e-6
    ext = lh.extrapolate_levels({"2016": levels, "2019": {s: {b: {k: v * 1.1 for k, v in d.items()} for b, d in x.items()}
                                                         for s, x in levels.items()}}, 2019, 2021, window=3)
    assert abs(ext["2021"]["남자"]["40"]["mean"] / ext["2019"]["남자"]["40"]["mean"] - 1.1 ** (2 / 3)) < 1e-6
    assert lh.fmt_amount(2346.7) == "2,350만원"


def test_eligible_rule_axes_and_undetermined():
    worker = {"age": 30, "province": "서울", "marital": "미혼", "working": True, "income_q": 1, "income_amt": 1800.0}
    rich = {**worker, "income_amt": 4200.0}
    idle = {**worker, "working": False, "income_amt": None}
    idle_with_amt = {**worker, "working": False}  # worked in 2024, not in 2025: the block shows no income line
    unknown = {**worker, "working": None, "income_amt": None}
    rule = {"income_max_manwon": 2000, "working": True}
    assert lh.eligible(rule, worker) is True and lh.eligible(rule, rich) is False
    assert lh.eligible(rule, idle) is False  # the working axis is definitely violated, even though income is unknown
    assert lh.eligible({"income_max_manwon": 2000}, idle) is None and lh.eligible({"income_max_manwon": 2000}, idle_with_amt) is None
    assert lh.eligible({"working": True}, unknown) is None and lh.eligible({"income_min_manwon": 1000}, worker) is True
    assert lh.eligible({"age_min": 19, "age_max": 34}, worker) is True and lh.eligible({"age_max": 29}, worker) is False
    assert lh.eligible({"capital": True}, worker) is True and lh.eligible({"capital": False}, worker) is False
    assert lh.eligible({"capital": True}, {**worker, "province": "경상남"}) is False
    assert lh.eligible({"capital": True}, {**worker, "province": "화성"}) is None
    assert lh.eligible({}, unknown) is True  # no axis: everyone fits (callers reject empty rules)


def test_rule_text():
    assert lh.rule_text({"income_max_manwon": 2000, "working": True}) == "개인 근로·사업소득 연 2,000만 원 이하 · 일함"
    assert lh.rule_text({"income_min_manwon": 1000, "income_max_manwon": 3000, "age_min": 19, "age_max": 34, "capital": True}) \
        == "개인 근로·사업소득 연 1,000~3,000만 원 · 만 19~34세 · 수도권"
    assert lh.rule_text({"income_min_manwon": 500, "working": False, "age_max": 29}) == "개인 근로·사업소득 연 500만 원 이상 · 일하지 않음 · 만 29세 이하"
    assert lh.rule_text({"age_min": 65, "capital": False, "note": "x"}) == "만 65세 이상 · 비수도권"


def test_state_block_and_future_profile_state_only():
    person = {"uuid": "u", "age": 28, "province": "강원", "sex": "남자", "age_band": "19–29세",
              "profile": "이름: 이현우\n성별·나이: 남자, 28세\n사는 곳: 강원-원주시 (강원)\n직업: 육군 병사\n"
                         "학력: 4년제 대학교 / 혼인: 미혼\n가구: 기타3세대 / 주거: 아파트\n\n이야기.\n\n"
                         "[공공통계로 배정한 생활 여건 — 가정]\n- 주거 점유: 월세\n- 일하는 형태: 임금근로자\n- 출퇴근 수단: 버스"}
    hist = {"residence": {"2025": "강원"}, "marital": {"2025": "미혼"}, "employed": {"2025": True},
            "income_q": {"2024": 2}, "income_amt": {"2024": 2346.0}}
    now = lh.now_state(person, hist)
    block = lh.state_block(now, lh.BASE_YEAR, amount_year=2024)
    assert "2025년이고, 이 사람은 28세" in block and "- 개인 근로·사업소득: 2024년 연 2,350만원" in block
    assert "→" not in block and "%" not in block  # states only, never change sentences
    then = {"alive": True, "age": 33, "province": "경기", "marital": "배우자있음", "working": False, "income_q": None,
            "income_amt": None}
    text = lh.future_profile(person, then)
    head = text.split("\n\n")[0]
    assert "성별·나이: 남자, 33세" in head and "사는 곳: 경기" in head and "혼인: 배우자있음\n" in head
    assert "직업: 육군 병사 (2030년 현재는 일하지 않음)" in head
    assert "일하는 형태" not in text and "출퇴근" not in text and "- 주거 점유: 월세" in text
    assert text.endswith("- 일: 일하지 않음") and "근로·사업소득" not in text.split("[2030년")[-1]
    assert lh.state_changes(now, then) == ["working", "province", "marital"]
    # a header that continues after 혼인 keeps its separator
    person2 = {**person, "profile": "학력: 고졸 / 혼인: 미혼 / 가구: 1인"}
    assert "혼인: 배우자있음 / 가구: 1인" in lh.future_profile(person2, then)
