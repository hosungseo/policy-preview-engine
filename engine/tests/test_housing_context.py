import re
from collections import Counter

from pp import housing_context as hc

GANGNAM = {"uuid": "u-1", "district": "서울-강남구", "province": "서울", "housing_type": "아파트", "age": 30,
           "family_type": "혼자 거주"}


def person(**kw):
    return {**GANGNAM, **kw}


def test_head_age_and_bands():
    assert hc.head_age(person(age=25, family_type="부모와 동거")) == 53
    assert hc.head_age(person(age=17, family_type="조부모와 동거")) == 67
    assert hc.head_age(person(age=40, family_type="배우자·자녀와 거주")) == 40
    assert hc.age_band(53, single=False) == "50 ~ 54세"
    assert hc.age_band(27, single=True) == "25~29"
    assert hc.age_band(90, single=False) == "85세이상" and hc.age_band(90, single=True) == "85세 이상"


def test_tenure_probs_follow_age_and_household():
    young_single = hc.tenure_probs(person(age=28, family_type="혼자 거주"))
    older_couple = hc.tenure_probs(person(age=62, family_type="배우자와 거주"))
    child_at_home = hc.tenure_probs(person(age=28, family_type="부모와 동거"))
    for p in (young_single, older_couple, child_at_home):
        assert set(p) == set(hc.TENURES) and abs(sum(p.values()) - 1) < 1e-6
    assert young_single["own"] < 0.2 < older_couple["own"]
    assert child_at_home["own"] > young_single["own"]  # lives in the parents' household


def test_survey_factors_scale_to_2024_province_shares():
    t = hc.tables()
    census_seoul = t["census"]["11"]
    f = hc._survey_factors("서울", census_seoul)
    c = hc._collapse(census_seoul["housing"]["계"])
    assert abs(c["own"] * f["own"] - t["survey2024"]["own"]["서울"]) < 1e-9
    assert abs((c["jeonse"] + c["monthly"]) * f["jeonse"] - t["survey2024"]["rent"]["서울"]) < 1e-9


def test_assign_is_seeded_and_matches_probabilities():
    p = person(age=45, family_type="배우자·자녀와 거주")
    assert hc.assign(p) == hc.assign(p)
    draws = Counter(hc.assign(person(uuid=f"u-{i}", age=45, family_type="배우자·자녀와 거주"))["tenure"] for i in range(4000))
    probs = hc.tenure_probs(p)
    for k in hc.TENURES:
        assert abs(draws[k] / 4000 - probs[k]) < 0.03
    owners = [hc.assign(person(uuid=f"u-{i}", age=45, family_type="배우자·자녀와 거주")) for i in range(400)]
    assert all((a["multi_home"] is None) == (a["tenure"] != "own") for a in owners)


def _cell(small=False):
    return {"trade": {"n": 50, "median": 265000.0, "median_per_m2": 3000.0, "over_6": 0.99, "over_15": 0.84,
                      "over_25": 0.54, "small": small},
            "rent": {"n": 90, "monthly_share": 0.4, "jeonse_median": 110000.0, "monthly_rent_median": 250.0,
                     "monthly_deposit_median": 10000.0, "small": small}}


def test_housing_block_lists_tenure_market_and_ownership_facts():
    market = {"windows": {"m": ["202503", "202504", "202505"]},
              "districts": {"서울-강남구": {"m": {"Apt": _cell()}}}}
    text = hc.housing_block(person(), {"tenure": "own", "multi_home": True}, "m", market)
    assert "자가(아파트), 집 2채 이상 보유" in text
    assert "서울 강남구 실거래(2025년 3~5월)" in text
    assert "매매 중위 26.5억 원" in text and "15억 원 초과 거래 84%" in text and "전세 중위 11.0억 원" in text
    assert "월세 중위 250만 원(보증금 1.0억 원)" in text
    assert "공시가격 기준 12억 원 초과" in text
    small = {"windows": market["windows"], "districts": {"서울-강남구": {"m": {"Apt": _cell(small=True)}}}}
    assert "실거래" not in hc.housing_block(person(), {"tenure": "jeonse", "multi_home": None}, "m", small)
    assert "전세(아파트)" in hc.housing_block(person(), {"tenure": "jeonse", "multi_home": None}, "m", small)


def test_placebo_has_the_block_shape_and_no_facts():
    assert hc.PLACEBO.startswith("주거 정보") and len(hc.PLACEBO.splitlines()) == 4
    assert not re.search(r"\d", hc.PLACEBO)


def test_price_band_uses_the_whole_period_level():
    market = {"levels": {"서울-강남구": {"median": 255000.0, "small": False}, "서울-노원구": {"median": 60000.0, "small": False},
                         "경상북-안동시": {"median": 13200.0, "small": False}, "인천-옹진군": {"median": 9000.0, "small": True}}}
    assert hc.price_band("서울-강남구", market) == "15억 원 이상"
    assert hc.price_band("서울-노원구", market) == "6억~9억 원"  # a floor belongs to the band above it
    assert hc.price_band("경상북-안동시", market) == "3억 원 미만"
    assert hc.price_band("인천-옹진군", market) == hc.NO_PRICE == hc.price_band("없는-구", market)
    assert hc.PRICE_BAND_ORDER[0] == "15억 원 이상" and hc.PRICE_BAND_ORDER[-1] == hc.NO_PRICE


def test_examples_are_the_blocks_those_homes_get():
    market = {"windows": {"m": ["202503", "202504", "202505"]}, "districts": {"서울-강남구": {"m": {"Apt": _cell()}}}}
    ex = hc.examples("m", market)
    assert [e["label"] for e in ex][0] == "서울 강남구 · 아파트 자가 · 2채 이상"
    assert ex[0]["text"] == hc.housing_block(hc.EXAMPLE_HOMES[0], hc.EXAMPLE_HOMES[0], "m", market)
    assert "월세(다세대주택)" in ex[1]["text"] and ex[1]["label"].endswith("다세대주택 월세")
