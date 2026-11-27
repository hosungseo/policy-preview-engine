import pytest

from pp import analyze_jev as aj


def person(uuid, age=30, province="서울", major="사무 종사자", family="혼자 거주", sex="남자"):
    return {"uuid": uuid, "age": age, "province": province, "occupation_major": major, "family_type": family,
            "sex": sex, "education_level": "고등학교", "housing_type": "아파트"}


def row(uuid, stance, probs, direct=0.5, comment=0.5, channel="none", segs=None):
    return {"uuid": uuid, "stance": stance, "stance_probs": probs, "stance_conf": 0.7,
            "reserve": round(sum(probs[:3]), 4), "direct": direct, "comment": comment, "channel": channel,
            "channel_probs": {channel: 1.0}, "segments": segs or {"s1": 0.5}}


def test_overall_mass_and_mean():
    rows = [row("a", -1.0, [0.2, 0.6, 0.2, 0, 0]), row("b", 1.0, [0, 0, 0.2, 0.6, 0.2])]
    out = aj.overall(rows)
    assert out["n"] == 2 and out["mean"] == 0.0
    assert out["mass"] == [0.1, 0.3, 0.2, 0.3, 0.1]
    lo, hi = out["ci95"]
    assert lo <= 0 <= hi


def test_by_group_uses_expected_stance_and_flags_small():
    people = {f"y{i}": person(f"y{i}", age=25) for i in range(40)} | {f"o{i}": person(f"o{i}", age=75) for i in range(5)}
    rows = [row(u, 1.0 if u.startswith("y") else -1.5, [0, 0, 0, 1, 0]) for u in people]
    groups = aj.by_group(rows, people)["age_band"]
    assert groups[0]["group"] == "19–29세" and groups[0]["small"] is False and groups[0]["mean"] == 1.0
    assert groups[1]["small"] is True and groups[1]["n"] == 5


def test_clause_matrix():
    people = {f"p{i}": person(f"p{i}", age=25 if i < 30 else 75) for i in range(60)}
    rows = [row(u, 0.0, [0, 0, 1, 0, 0], segs={"s1": 0.9 if int(u[1:]) < 30 else 0.1, "s2": 0.2}) for u in people]
    m = aj.clause_matrix(rows, people, [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}])
    assert m["overall"] == {"s1": 0.5, "s2": 0.2}
    ages = {g["group"]: g for g in m["groups"]["age_band"]}
    assert ages["19–29세"]["values"]["s1"] == 0.9 and ages["70세 이상"]["values"]["s1"] == 0.1


def test_channels_share():
    rows = [row("a", 0, [0, 0, 1, 0, 0], channel="senior_center"), row("b", 0, [0, 0, 1, 0, 0], channel="senior_center"),
            row("c", 0, [0, 0, 1, 0, 0], channel="none")]
    ch = aj.channels(rows)
    assert ch[0]["key"] == "senior_center" and ch[0]["share"] == pytest.approx(0.667, abs=0.001)
    assert ch[0]["label"] == "경로당·노인복지관"


def test_outreach_candidates_from_jev():
    people, rows = {}, []
    for i in range(40):  # affected, not supportive, silent farmers
        people[f"f{i}"] = person(f"f{i}", age=72, province="경상북", major="농림어업 숙련 종사자")
        rows.append(row(f"f{i}", -1.0, [0.3, 0.5, 0.2, 0, 0], direct=0.9, comment=0.1, channel="senior_center"))
    for i in range(40):  # supportive office workers who would speak up
        people[f"o{i}"] = person(f"o{i}", age=35, major="사무 종사자", family="배우자와 거주")
        rows.append(row(f"o{i}", 1.5, [0, 0, 0, 0.5, 0.5], direct=0.2, comment=0.8))
    llm_people = {"v1": person("v1", age=70, province="경상북", major="농림어업 숙련 종사자"), "v2": person("v2", age=35)}
    top = aj.outreach_candidates(rows, people, llm_people)
    assert top[0]["group"] in ("농림어업 숙련 종사자", "70세 이상 · 대경권", "1인 가구")
    farmer = next(c for c in top if c["group"] == "농림어업 숙련 종사자")
    assert farmer["oppose"] == pytest.approx(1.0) and farmer["silent"] == pytest.approx(0.9)
    assert farmer["member_uuids"] == ["v1"] and farmer["channels"][0] == "경로당·노인복지관"
    assert all(c["group"] != "사무 종사자" or c["score"] < farmer["score"] for c in top)


def test_compare_llm_and_jev():
    reactions = [{"uuid": "a", "support": 1}, {"uuid": "b", "support": 1}, {"uuid": "c", "support": 0}, {"uuid": "z", "support": 2}]
    rows = {"a": row("a", -0.5, [0.2, 0.3, 0.3, 0.2, 0]), "b": row("b", 0.5, [0, 0.1, 0.4, 0.3, 0.2]),
            "c": row("c", 0.0, [0, 0.2, 0.6, 0.2, 0])}
    cmp = aj.compare(reactions, rows)
    assert cmp["n"] == 3
    assert cmp["llm_dist"] == {"-2": 0, "-1": 0, "0": 1, "1": 2, "2": 0}
    assert cmp["llm_favor"] == pytest.approx(0.667, abs=0.001)
    assert cmp["jev_favor"] == pytest.approx((0.2 + 0.5 + 0.2) / 3, abs=0.001)
    assert cmp["jev_mass"][2] == pytest.approx((0.3 + 0.4 + 0.6) / 3, abs=0.001)


def xrow(uuid, **extra):
    base = row(uuid, 0.5, [0, 0.1, 0.3, 0.4, 0.2])
    base.update(extra)
    return base


def test_position_matrix_derives_support_from_mean_and_oppose():
    people = {f"y{i}": person(f"y{i}", age=25) for i in range(30)} | {f"o{i}": person(f"o{i}", age=75) for i in range(30)}
    rows = [xrow(u, positions={"s1": -0.6 if u.startswith("o") else 0.4}, pos_oppose={"s1": 0.7 if u.startswith("o") else 0.1})
            for u in people]
    m = aj.position_matrix(rows, people, [{"id": "s1", "label": "가"}])
    assert m["overall"]["s1"] == {"mean": -0.1, "oppose": 0.4, "support": 0.3}
    ages = {g["group"]: g for g in m["groups"]["age_band"]}
    assert ages["70세 이상"]["values"]["s1"] == -0.6 and ages["70세 이상"]["oppose"]["s1"] == 0.7
    assert aj.position_matrix([row("x", 0, [0, 0, 1, 0, 0])], {"x": person("x")}, [{"id": "s1", "label": "가"}]) is None


def test_issue_prevalence_and_leading_groups():
    people = {f"y{i}": person(f"y{i}", age=25) for i in range(40)} | {f"o{i}": person(f"o{i}", age=75) for i in range(40)}
    rows = [xrow(u, issues={"0": 0.8 if u.startswith("o") else 0.2, "1": 0.3}) for u in people]
    issues = [{"id": "i1", "k": 0, "title": "요금"}, {"id": "i2", "k": 1, "title": "안전"}]
    prev = aj.issue_prevalence(rows, people, issues)
    assert prev["overall"] == {"i1": 0.5, "i2": 0.3}
    assert prev["leaders"]["i1"][0] == {"kind": "연령대", "group": "70세 이상", "n": 40, "mean": 0.8, "lift": 1.6}
    assert prev["leaders"]["i2"] == []


def test_methods_overall_matrix_and_outreach():
    people, rows = {}, []
    for i in range(40):
        people[f"f{i}"] = person(f"f{i}", age=72, province="경상북", major="농림어업 숙련 종사자")
        rows.append(row(f"f{i}", -1.0, [0.3, 0.5, 0.2, 0, 0], direct=0.9, comment=0.1, channel="senior_center")
                    | {"methods": {"local_visit": 0.7, "phone": 0.5, "portal": 0.1, "town_hall": 0.3, "text_survey": 0.2, "workplace": 0.05}})
    overall = aj.methods_overall(rows)
    assert overall[0] == {"key": "local_visit", "label": "경로당·마을 모임 방문 청취", "p": 0.7}
    top = aj.outreach_candidates(rows, people, {})
    assert [m["key"] for m in top[0]["methods"]] == ["local_visit", "phone", "town_hall"]
    matrix = aj.methods_matrix(rows, people)
    assert matrix["age_band"][0]["values"]["local_visit"] == 0.7


def test_explain_summary_and_understanding():
    people = {f"a{i}": person(f"a{i}") for i in range(30)} | {f"b{i}": {**person(f"b{i}"), "education_level": "초등학교"} for i in range(30)}
    rows = [xrow(u, explain={"s1": 0.2, "s2": 0.8}, understand=0.3 if u.startswith("b") else 0.7) for u in people]
    ex = aj.explain_summary(rows, people, [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}])
    assert ex["overall"] == {"s1": 0.2, "s2": 0.8} and ex["top"] == "s2"
    edu = {g["group"]: g for g in ex["understand"]["education_level"]}
    assert ex["understand"]["overall"] == 0.5 and edu["초등학교"]["mean"] == 0.3


def test_provinces_use_display_names():
    people = {f"p{i}": person(f"p{i}", province="경상남") for i in range(3)} | {"s": person("s", province="서울")}
    rows = [row(u, 1.0 if u == "s" else -1.0, [0, 0, 0.5, 0.5, 0] if u == "s" else [0.5, 0.5, 0, 0, 0]) for u in people]
    tiles = {t["province"]: t for t in aj.provinces(rows, people)}
    assert tiles["경남"]["n"] == 3 and tiles["경남"]["mean"] == -1.0 and tiles["서울"]["reserve"] == 0.5


def test_alternatives_summary_is_paired():
    people = {f"o{i}": person(f"o{i}", age=67) for i in range(40)} | {f"y{i}": person(f"y{i}", age=30) for i in range(40)}
    rows = []
    for u in people:
        old = u.startswith("o")
        rows.append({"uuid": u, "variant": "base", "stance": -1.0 if old else 0.5,
                     "probs": [0.3, 0.5, 0.2, 0, 0] if old else [0, 0, 0.5, 0.5, 0]})
        rows.append({"uuid": u, "variant": "a1", "stance": 0.5 if old else 0.3,
                     "probs": [0, 0, 0.5, 0.5, 0] if old else [0, 0.1, 0.5, 0.4, 0]})
    rows.append({"uuid": "stray", "variant": "a1", "stance": 2.0, "probs": [0, 0, 0, 0, 1]})
    drafts = [{"id": "a1", "title": "저소득 예외", "text": "[수정안] ..."}]
    out = aj.alternatives_summary(rows, people, drafts)
    assert out["baseline"]["n"] == 80 and out["baseline"]["mean"] == -0.25
    item = out["items"][0]
    assert item["n"] == 80 and item["d_mean"] == 0.65 and item["d_reserve"] == pytest.approx(-0.2, abs=1e-4)
    assert item["movers"][0]["group"] == "60대" and item["movers"][0]["d_mean"] == 1.5


def test_alternatives_net_of_placebo():
    people = {f"o{i}": person(f"o{i}", age=67) for i in range(40)}
    rows = []
    for u in people:
        rows.append({"uuid": u, "variant": "base", "stance": 0.0, "probs": [0, 0, 1, 0, 0]})
        rows.append({"uuid": u, "variant": "p0", "stance": -0.1, "probs": [0, 0.1, 0.9, 0, 0]})
        rows.append({"uuid": u, "variant": "a1", "stance": 0.3, "probs": [0, 0, 0.7, 0.3, 0]})
    out = aj.alternatives_summary(rows, people, [{"id": "a1", "title": "x", "text": "[수정안] x"}], placebo_id="p0")
    assert out["placebo"] == {"n": 40, "d_favor": 0.0, "d_reserve": 0.0, "d_mean": -0.1}
    item = out["items"][0]
    assert item["d_mean"] == 0.3 and item["net_mean"] == 0.4 and item["net_reserve"] == -0.3


def test_question_priority_ranks_and_names_leading_groups():
    people = {f"o{i}": person(f"o{i}", age=72) for i in range(40)} | {f"y{i}": person(f"y{i}", age=25) for i in range(40)}
    rows = [{"uuid": u, "asks": {"0": 0.9 if u.startswith("o") else 0.1, "1": 0.3}} for u in people]
    prio = aj.question_priority(rows, people, [{"question": "q0"}, {"question": "q1"}])
    assert prio[0]["p"] == 0.5 and prio[1]["p"] == 0.3
    assert prio[0]["leaders"][0] == {"kind": "연령대", "group": "70세 이상", "n": 40, "mean": 0.9, "lift": 1.8}
    assert prio[1]["leaders"] == []


def test_hearing_trajectories_track_each_participant():
    reads = [{"index": 1, "round": 1, "speaker": "u1", "stance": -1.5, "marks": {"rebut": 0.1, "new_point": 0.8, "concede": 0.0, "proposal": 0.2}},
             {"index": 2, "round": 1, "speaker": "u2", "stance": 1.0, "marks": {"rebut": 0.2, "new_point": 0.7, "concede": 0.1, "proposal": 0.1}},
             {"index": 4, "round": 2, "speaker": "u1", "stance": -1.2, "marks": {"rebut": 0.9, "new_point": 0.3, "concede": 0.2, "proposal": 0.1}},
             {"index": 5, "round": 2, "speaker": "u2", "stance": 1.1, "marks": {"rebut": 0.8, "new_point": 0.2, "concede": 0.1, "proposal": 0.0}},
             {"index": 7, "round": 3, "speaker": "u1", "stance": -0.4, "marks": {"rebut": 0.1, "new_point": 0.1, "concede": 0.7, "proposal": 0.9}},
             {"index": 8, "round": 3, "speaker": "u2", "stance": 1.0, "marks": {"rebut": 0.1, "new_point": 0.1, "concede": 0.2, "proposal": 0.6}}]
    out = aj.hearing_trajectories(reads, ["u1", "u2"])
    first = out["participants"][0]
    assert first["uuid"] == "u1" and first["stances"] == {"1": -1.5, "2": -1.2, "3": -0.4} and first["change"] == 1.1
    assert out["movers"] == ["u1"] and out["counts"] == {"rebut": 2, "new_point": 2, "concede": 1, "proposal": 2}


def test_occupation_agreement_lists_disagreements():
    jev_map = {"택시 운전원": "장치·기계 조작 및 조립 종사자", "건물 청소원": "서비스 종사자", "교사": "전문가 및 관련 종사자"}
    llm_map = {"택시 운전원": "장치·기계 조작 및 조립 종사자", "건물 청소원": "단순노무 종사자", "교사": "전문가 및 관련 종사자"}
    out = aj.occupation_agreement(jev_map, llm_map)
    assert out["n"] == 3 and out["agree"] == 2 and out["share"] == 0.667
    assert out["examples"] == [{"occupation": "건물 청소원", "jev": "서비스 종사자", "llm": "단순노무 종사자"}]


def test_lens_summary_counts_and_support():
    tags = {"r1": {"cost": 0.9, "welcome": 0.1}, "r2": {"cost": 0.6, "welcome": 0.2}, "r3": {"cost": 0.1, "welcome": 0.8}}
    reactions = [{"rid": "r1", "support": -1}, {"rid": "r2", "support": 0}, {"rid": "r3", "support": 2}]
    out = aj.lens_summary(tags, reactions, {"cost": "생계·비용 부담", "welcome": "기대·환영"})
    assert out["items"][0] == {"key": "cost", "label": "생계·비용 부담", "n": 2, "share": 0.667, "mean_support": -0.5}
    assert out["items"][1]["key"] == "welcome" and out["items"][1]["n"] == 1 and out["threshold"] == 0.5
