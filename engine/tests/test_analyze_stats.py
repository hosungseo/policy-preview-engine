from pp import analyze_stats as st


def person(uuid, age=30, province="서울", sex="남자", major="사무 종사자", family="혼자 거주"):
    return {"uuid": uuid, "age": age, "province": province, "sex": sex, "education_level": "고등학교",
            "housing_type": "아파트", "family_type": family, "occupation_major": major}


def reaction(uuid, support, impact="직접", would=False, channel="경로당", seg=None, concerns=()):
    return {"uuid": uuid, "rid": f"r{uuid}", "support": support, "impact": impact, "would_comment": would,
            "channel": channel, "segment_id": seg, "concerns": list(concerns), "reason": f"이유 {uuid}"}


def test_overall_mean_distribution_and_ci():
    rs = [reaction(str(i), s) for i, s in enumerate([2, 2, -2, 0])]
    out = st.overall(rs)
    assert out["n"] == 4 and out["mean"] == 0.5
    assert out["dist"] == {"-2": 1, "-1": 0, "0": 1, "1": 0, "2": 2}
    lo, hi = out["ci95"]
    assert lo <= 0.5 <= hi
    assert st.overall([])["n"] == 0


def test_by_group_orders_and_flags_small_groups():
    people = {str(i): person(str(i), age=25 if i < 12 else 75) for i in range(15)}
    rs = [reaction(str(i), 1 if i < 12 else -2) for i in range(15)]
    groups = st.by_group(rs, people)
    ages = groups["age_band"]
    assert [g["group"] for g in ages] == ["19–29세", "70세 이상"]
    assert ages[0]["small"] is False and ages[1]["small"] is True
    assert ages[1]["mean"] == -2 and ages[1]["oppose"] == 1.0


def test_segment_heat():
    rs = [reaction("1", -1, seg="s1", concerns=["요금"]), reaction("2", 1, seg="s1", concerns=["요금", "안전"]),
          reaction("3", 2, seg=None)]
    heat = st.segment_heat(rs, [{"id": "s1"}, {"id": "s2"}])
    assert heat[0]["mentions"] == 2 and heat[0]["mean"] == 0 and heat[0]["top_concerns"][0] == "요금"
    assert heat[1] == {"segment_id": "s2", "mentions": 0, "mean": None, "oppose": 0, "favor": 0, "top_concerns": []}


def test_outreach_candidates_rank_and_limits():
    people = {}
    rs = []
    for i in range(8):  # affected, opposed, silent farmers
        people[f"f{i}"] = person(f"f{i}", age=72, province="경상북", major="농림어업 숙련 종사자")
        rs.append(reaction(f"f{i}", -2, impact="직접", would=False))
    for i in range(8):  # mild office workers
        people[f"o{i}"] = person(f"o{i}", age=35, major="사무 종사자", family="배우자와 거주")
        rs.append(reaction(f"o{i}", 1, impact="간접", would=True))
    for i in range(3):  # too small
        people[f"s{i}"] = person(f"s{i}", age=50, major="군인")
        rs.append(reaction(f"s{i}", -2))
    top = st.outreach_candidates(rs, people)
    groups = {c["group"] for c in top}
    assert {"농림어업 숙련 종사자", "70세 이상 · 대경권"} <= groups
    assert "사무 종사자" not in groups
    assert all(c["n"] >= 5 for c in top)
    assert all(c["score"] > 0 for c in top)
    assert sum(c["kind"] == "직업군" for c in top) <= 2
    assert top[0]["channels"] == ["경로당"]


def test_insights_are_code_generated_sentences():
    analysis = {
        "issues": [{"title": "요금 부담", "share": 0.42}],
        "segments_heat": [{"segment_id": "s1", "mentions": 9, "mean": -0.8}],
        "by_group": {"age_band": [{"group": "70세 이상", "mean": -1.2, "n": 40, "small": False}]},
        "outreach": [{"group": "농림어업 숙련 종사자", "n": 12, "oppose": 0.75, "silent": 0.9}],
        "overall": {"n": 300, "mean": 0.1}, "overall_aff": {"n": 80, "mean": -0.6},
    }
    lines = st.insights(analysis, [{"id": "s1", "label": "가. 기준 연령 상향"}])
    assert any("‘요금 부담’" in x and "42%" in x for x in lines)
    assert any("가. 기준 연령 상향" in x and "9건" in x for x in lines)
    assert any("70세 이상" in x for x in lines)
    assert any("0.70 낮습니다" in x for x in lines)


def test_insights_include_jev_comparison():
    analysis = {"issues": [], "segments_heat": [], "by_group": {}, "outreach": [], "overall": {"n": 0}, "overall_aff": {"n": 0},
                "jev": {"n": 5000, "overall": {"mass": [0.1, 0.2, 0.2, 0.3, 0.2]},
                        "compare": {"n": 400, "llm_favor": 0.9975, "jev_favor": 0.45,
                                    "llm_dist": {"-2": 0, "-1": 0, "0": 1, "1": 379, "2": 20}}}}
    lines = st.insights(analysis, [])
    assert lines == ["5,000명 정량 점검(Jev)에서 찬성 쪽 확률은 평균 50%, 반대·유보 쪽은 50%입니다. "
                     "같은 400명 중 LLM은 399명이 찬성으로 답했고, Jev는 이 400명의 찬성 쪽 확률을 평균 45%로 봤습니다."]


def test_pct_never_rounds_to_the_extremes():
    assert [st.pct(x) for x in (0, 0.004, 0.0004, 0.5, 0.9975, 0.99996, 1)] == ["0%", "0.4%", "<0.1%", "50%", "99.8%", ">99.9%", "100%"]


def test_insights_cover_positions_methods_amendments_and_consistency():
    analysis = {
        "issues": [], "segments_heat": [], "by_group": {}, "overall": {"n": 0}, "overall_aff": {"n": 0},
        "jev": {"n": 5000, "overall": {"mass": [0.1, 0.2, 0.2, 0.3, 0.2]}, "compare": {},
                "positions": {"overall": {"s1": {"mean": 0.2, "oppose": 0.15, "support": 0.35},
                                          "s2": {"mean": -0.3, "oppose": 0.45, "support": 0.15}},
                              "groups": {"age_band": [{"group": "60대", "n": 900, "small": False, "values": {}, "oppose": {"s1": 0.2, "s2": 0.7}},
                                                      {"group": "70세 이상", "n": 12, "small": True, "values": {}, "oppose": {"s1": 0.1, "s2": 0.9}}]}}},
        "outreach": [{"group": "60대 · 동남권", "n": 146, "oppose": 0.62, "silent": 0.68,
                      "methods": [{"key": "local_visit", "label": "경로당·마을 모임 방문 청취", "p": 0.63}]}],
        "alternatives": {"n": 1500, "items": [{"title": "저소득 예외", "d_reserve": -0.083}, {"title": "안내 강화", "d_reserve": 0.01}]},
        "consistency": {"n": 400, "flagged": 7, "threshold": 1.5},
    }
    lines = st.insights(analysis, [{"id": "s1", "label": "가. 연령"}, {"id": "s2", "label": "나. 할인"}])
    assert any("‘나. 할인’" in x and "45%" in x and "60대(70%)" in x for x in lines)
    assert any("‘경로당·마을 모임 방문 청취’" in x and "63%" in x for x in lines)
    assert any("‘저소득 예외’" in x and "-8.3%p" in x and "1,500명" in x for x in lines)
    assert any("400건 중 7건" in x for x in lines)
    none_helped = st.insights({**analysis, "alternatives": {"n": 1500, "items": [{"title": "x", "d_reserve": 0.02}]}}, [])
    assert any("수정안 1개 모두 반대·유보를 줄이지 못했습니다" in x for x in none_helped)


def test_insight_names_least_supported_clause_when_nobody_opposes():
    analysis = {"issues": [], "segments_heat": [], "by_group": {}, "overall": {"n": 0}, "overall_aff": {"n": 0},
                "jev": {"n": 5000, "overall": {"mass": [0, 0, 0.3, 0.6, 0.1]}, "compare": {},
                        "positions": {"overall": {"s1": {"mean": 0.6, "oppose": 0.01, "support": 0.61},
                                                  "s2": {"mean": 0.1, "oppose": 0.05, "support": 0.15}}, "groups": {}}}}
    lines = st.insights(analysis, [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}])
    assert any("반대 확률이 10%를 넘은 조항은 없습니다" in x and "‘나’" in x and "15%" in x for x in lines)


def test_insight_reports_unclear_clauses_and_missing_notice_items():
    analysis = {"issues": [], "segments_heat": [], "by_group": {}, "overall": {"n": 0}, "overall_aff": {"n": 0},
                "clarity": {"flagged": 2, "clauses": 5, "worst": {"segment_id": "s2", "flags": ["대상 모호", "기준·숫자 누락"]},
                            "missing": ["재정·비용 추계", "검토한 대안"]}}
    lines = st.insights(analysis, [{"id": "s2", "label": "나. 예외"}])
    assert any("조항 5개 중 2개" in x and "‘나. 예외’" in x and "대상 모호·기준·숫자 누락" in x
               and "재정·비용 추계, 검토한 대안" in x for x in lines)
