from pp import life_context as lc
import copy

import pytest

BASE = {"uuid": "u-1", "district": "서울-강남구", "province": "서울", "housing_type": "아파트", "age": 45, "sex": "남자",
        "family_type": "배우자·자녀와 거주", "occupation": "마케팅 전문가", "education_level": "4년제 대학교",
        "profile": "이름: 가\n성별·나이: 남자, 45세\n\n가 씨는 성실한 직장인입니다."}


def person(i: int, **kw) -> dict:
    return {**BASE, "uuid": f"u-{i}", **kw}


def small_panel() -> list[dict]:
    people = []
    for i in range(400):
        people.append(person(
            i, age=20 + i % 60, sex="남자" if i % 2 else "여자",
            district=("서울-강남구", "서울-노원구", "경상북-안동시")[i % 3],
            province=("서울", "서울", "경상북")[i % 3],
            family_type=("혼자 거주", "배우자와 거주", "배우자·자녀와 거주", "부모와 동거")[i % 4],
            occupation="무직" if i % 5 == 0 else "사무 보조원",
            education_level=("고등학교", "4년제 대학교", "중학교")[i % 3]))
    return people


@pytest.mark.parametrize("occupation", ["전직 교사, 현재 구직중", "전직 사무원 (현재 구직 중)",
                                       "구직중", "구직자", "취업 준비 중", "무직", "", None])
def test_current_jobless_status_overrides_former_job(occupation):
    p = person(1, occupation=occupation)
    assert not lc.working(p)
    assert lc.employment_status(p, 2026) is None


@pytest.mark.parametrize("occupation", ["구직 상담원", "취업 상담사", "교사", "전직 교사, 현재 사무원"])
def test_job_titles_are_not_mistaken_for_jobless_status(occupation):
    assert lc.working(person(1, occupation=occupation))


def test_seekers_receive_no_worker_attributes_or_commute():
    from pp import survey_match

    people = [person(i, occupation="전직 사무원, 현재 구직중", marital_status="배우자있음") for i in range(40)]
    assigned, _ = lc.build(people)
    for p in people:
        a = assigned[p["uuid"]]
        assert "employment" not in a and "nonregular" not in a
        assert a["commute"] is None and a["value_status"]["commute"] == "not_applicable"
        assert a["dual_earner"] is False
        for key in ("night_work", "shift_work", "long_hours", "worker_care", "sleep_trouble"):
            assert key not in a
        assert survey_match.member("취업자", p, a) is False
        assert survey_match.member("미취업자", p, a) is True
        assert "일하는 형태" not in lc.block(a, "work")
        assert "출퇴근 수단" not in lc.block(a, "work")


def test_benefit_asset_consistency_preserves_receipts_and_allows_other_wealth():
    people = [person(i, age=70) for i in range(180)]
    out = {p["uuid"]: {"income": "10_30", "value_status": {},
                        "livelihood": i % 3 == 0, "basic_pension": i % 3 == 1}
           for i, p in enumerate(people)}
    before = copy.deepcopy(out)
    tenure = {p["uuid"]: "own" for p in people}
    gap = lc.assign_networth(people, out, tenure, 2026)
    for uid, a in out.items():
        assert a["livelihood"] == before[uid]["livelihood"]
        assert a["basic_pension"] == before[uid]["basic_pension"]
        if a["livelihood"] or a["basic_pension"]:
            assert a["networth"] in ("1", "2", "3", "4")
    assert any(a["networth"] == "5" for a in out.values())
    repeated = copy.deepcopy(before)
    assert lc.assign_networth(people, repeated, tenure, 2026) == gap
    assert repeated == out


def test_missing_or_unsupported_asset_distribution_remains_unknown(monkeypatch):
    t = copy.deepcopy(lc.tables())
    for q in lc.QUINTILES:
        t["networth"]["income_given_quintile"][q]["lt10"] = 0 if q != "5" else 1
        t["networth"]["income_given_quintile"][q]["10_30"] = None if q == "5" else .1
    monkeypatch.setattr(lc, "tables", lambda: t)
    people = [person(1), person(2)]
    out = {p["uuid"]: {"income": band, "livelihood": True, "value_status": {}}
           for p, band in zip(people, ("lt10", "10_30"))}
    assert lc.assign_networth(people, out, {p["uuid"]: "own" for p in people}, 2026) is None
    assert all(a["networth"] is None and a["value_status"]["networth"] == "unknown" for a in out.values())


def test_rake_matches_every_constraint_when_consistent():
    start = {"a": 0.5, "b": 0.5}
    cons = [(list(range(0, 50)), {"a": 0.8, "b": 0.2}), (list(range(50, 100)), {"a": 0.3, "b": 0.7})]
    probs, gap = lc.rake(100, start, cons)
    assert gap < 1e-3
    assert abs(sum(p["a"] for p in probs[:50]) / 50 - 0.8) < 1e-3
    assert all(abs(sum(p.values()) - 1) < 1e-9 for p in probs)


def test_rake_mean_constraint_tilts_toward_target():
    start = {"lo": 0.5, "hi": 0.5}
    probs, gap = lc.rake(10, start, [(list(range(10)), {"mean": 8000})], values={"lo": 2000, "hi": 10000})
    mean = sum(p["lo"] * 2000 + p["hi"] * 10000 for p in probs) / 10
    assert abs(mean - 8000) < 10 and gap < 1e-2


def test_build_is_deterministic_and_complete():
    people = small_panel()
    a1, _ = lc.build(people)
    a2, _ = lc.build(people)
    assert a1 == a2
    for p in people:
        a = a1[p["uuid"]]
        assert a["tenure"] in ("own", "jeonse", "monthly", "free")
        assert a["income"] in lc.INCOME_BANDS
        assert isinstance(a["debt"], bool) and isinstance(a["car"], bool)
        assert (a["commute"] is not None) == (p["occupation"] != "무직")
        if p["occupation"] == "무직":
            assert a["value_status"]["commute"] == "not_applicable"
        if a.get("livelihood"):
            assert a["income"] in lc.LOW_INCOME


def test_profile_text_mentions_skip_the_attribute():
    people = small_panel()
    people[0] = {**people[0], "profile": "헤더\n\n가 씨는 하루 한 갑씩 담배를 피우며, 주말마다 교회에 나가고 전세로 삽니다."}
    a, _ = lc.build(people)
    first = a[people[0]["uuid"]]
    assert {"smoking", "religion", "tenure"} <= set(first["skipped"])
    assert "smoking" not in first and "religion" not in first
    block = lc.block(first)
    assert "흡연" not in block and "종교" not in block and "주거 점유" not in block


def test_header_occupation_does_not_count_as_a_mention():
    p = person(1, profile="직업: 지게차 운전원\n\n가 씨는 성실합니다.")
    assert lc.mentions(p) == set()


def test_block_states_rare_attributes_only_when_present():
    a = {"tenure": "monthly", "skipped": [], "income": "10_30", "debt": False, "car": False, "livelihood": False,
         "disability": False, "smoking": True, "health_good": False, "religion": "none", "commute": "subway"}
    text = lc.block(a)
    assert "사실이 아니라" in text and "월세" in text and "1천만~3천만 원" in text and "전철·지하철" in text
    assert "수급" not in text and "장애" not in text and "건강" not in text
    assert "기초생활보장 수급 가구" in lc.block({**a, "livelihood": True})
    assert "등록 장애인" in lc.block({**a, "disability": True})


def test_basic_pension_fills_the_rate_from_the_lowest_incomes():
    people = [person(i, age=70, family_type="배우자와 거주", occupation="무직") for i in range(300)]
    a, _ = lc.build(people)
    got = [a[p["uuid"]] for p in people]
    share = sum(x["basic_pension"] for x in got) / len(got)
    assert abs(share - lc.tables()["basic_pension"]["70"]) < 0.08
    top = [x for x in got if x["income"] == "ge100"]
    low = [x for x in got if x["income"] in lc.LOW_INCOME]
    assert all(x["basic_pension"] for x in low) or not low
    assert sum(x["basic_pension"] for x in top) <= len(top) * 0.5


def test_chronic_diagnoses_start_at_30_and_appear_only_when_present():
    a, _ = lc.build(small_panel())
    young = [x for p, x in zip(small_panel(), a.values()) if p["age"] < 30 and "hypertension" in x]
    assert young and all(x["hypertension"] is None and x["diabetes"] is None for x in young)
    assert all(x["value_status"]["hypertension"] == x["value_status"]["diabetes"] == "not_applicable" for x in young)
    assert all(x["probs"]["hypertension"] is None and x["probs"]["diabetes"] is None for x in young)
    text = lc.block({"tenure": "own", "skipped": [], "hypertension": True, "diabetes": False, "health_good": False})
    assert "고혈압 진단 받음" in text and "당뇨" not in text and "건강" not in text


def test_addons_render_only_their_own_lines():
    a = {"tenure": "own", "skipped": [], "income": "30_50", "debt": True, "car": True, "networth": "2",
         "basic_pension": True, "employment": "wage", "nonregular": True, "dual_earner": True, "smoking": False,
         "function": "adl", "care": True, "digital": "poor", "religion": "buddhist"}
    full = lc.block(a)
    for text in ("자가", "3천만~5천만", "하위 20~40%", "기초연금", "임금근로자(비정규직)", "맞벌이", "비흡연",
                 "기본 일상생활", "돌봄 서비스", "찾기 어려워함", "불교"):
        assert text in full
    only = lc.block(a, "finance,digital")
    assert "3천만~5천만" in only and "찾기 어려워함" in only and "불교" not in only and "자가" not in only
    assert lc.block({"tenure": "own", "skipped": ["tenure"]}, "housing") == ""
    import pytest
    with pytest.raises(ValueError):
        lc.parse_addons("finance,bogus")


def test_new_addons_assign_and_render():
    people = small_panel()
    people[1] = {**people[1], "profile": "헤더\n\n가 씨는 주말마다 강아지와 산책하며 소설책을 즐겨 읽습니다."}
    a, _ = lc.build(people)
    first = a[people[1]["uuid"]]
    assert {"pet", "walking", "reading"} <= set(first["skipped"])
    assert "pet" not in first and "walking" not in first and "reading" not in first
    other = a[people[2]["uuid"]]
    for key in ("drinking", "obesity", "walking", "stress", "depression", "reading", "arts", "pet"):
        assert isinstance(other[key], bool)
    wage = [x for x in a.values() if x.get("employment") == "wage" and "nonregular" in x]
    assert wage and all(isinstance(x["employment_insurance"], bool) for x in wage)


def test_new_addon_lines():
    a = {"tenure": "own", "skipped": [], "employment": "wage", "nonregular": True, "employment_insurance": False,
         "drinking": True, "obesity": False, "walking": False, "stress": True, "depression": False,
         "reading": False, "arts": True, "pet": True}
    text = lc.block(a, "work,habits,mind,culture,pet")
    for s in ("비정규직, 고용보험 미가입", "고위험 음주", "스트레스를 많이 느낌", "한 권도 읽지 않음",
              "관람: 함", "반려동물을 키움"):
        assert s in text
    assert "비만" not in text and "우울감" not in text and "걷기" not in text
    assert "걷기 운동을 꾸준히 함" in lc.block({**a, "walking": True}, "habits")


def test_auto_addons_match_topics_not_substrings():
    core = set(lc.CORE_ADDONS)
    assert set(lc.auto_addons("이 정책에 찬성하십니까? 기술 혁신 지원")) == core
    assert set(lc.auto_addons("반려견 동물등록 의무화")) == core | {"pet"}
    assert set(lc.auto_addons("주류 광고 규제와 금연구역 확대")) == core | {"habits"}
    assert set(lc.auto_addons("청년 마음건강 상담 바우처")) == core | {"mind", "youth"}
    assert set(lc.auto_addons("공공도서관 야간 개관")) == core | {"culture"}


def test_survey_traits_assign_render_and_attach_by_topic():
    people = small_panel()
    a, _ = lc.build(people)
    for p in people:
        x = a[p["uuid"]]
        assert ("night_work" in x) == (p["occupation"] != "무직")
        assert ("senior_job" in x) == (p["age"] >= 65)
        assert isinstance(x["petition"], bool) and isinstance(x["unmet_care"], bool)
    text = lc.block({"tenure": "own", "skipped": [], "voted_general": False, "petition": True, "volunteer": False,
                     "private_insurance": False, "unmet_care": True, "night_work": True, "kiosk_hard": False},
                    "civic,medical,work,digital")
    for s in ("국회의원 선거에 투표하지 않음", "서명운동에 참여", "민간의료보험 미가입", "진료를 받지 못한", "밤 근무"):
        assert s in text
    assert "자원봉사" not in text and "키오스크" not in text
    assert set(lc.auto_addons("주민참여예산 공청회 개최")) == set(lc.CORE_ADDONS) | {"civic"}
    assert set(lc.auto_addons("실손보험 본인부담 상한")) == set(lc.CORE_ADDONS) | {"medical"}
    for p in people:
        x = a[p["uuid"]]
        assert ("youth_move" in x) == (19 <= p["age"] <= 34)
    assert "운전면허 없음" in lc.block({"tenure": "own", "skipped": [], "driving_license": False}, "mobility")
    assert lc.block({"tenure": "own", "skipped": [], "driving_license": True}, "mobility") == "" or \
        "운전면허" not in lc.block({"tenure": "own", "skipped": [], "driving_license": True}, "mobility")
    assert set(lc.auto_addons("고령 운전자 면허 반납 지원")) == set(lc.CORE_ADDONS) | {"mobility"}
