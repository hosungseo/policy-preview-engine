"""「찾아갈 곳」 (ppservice/survey/visit.py): cards only for differences worth reading, places from the full list."""
import pytest

from ppservice.survey import panel, visit
from tests.test_svc_survey import H, OPTIONS, QUESTION, _answers, api, drain, login  # noqa: F401

# Synthetic example policy (not a real case).
SPEC = {"title": "농어민 지원(합성 예시)", "policy_text": "농어민 직불금 지급 기준을 조정한다.", "question": QUESTION}


@pytest.mark.parametrize("profile", [
    "어린이집 교사로 일합니다.", "유치원 원장입니다.", "어린이집에서 근무합니다.",
    "유치원 근처에 거주합니다.", "어린이집 옆에 삽니다.", "신생아실 간호사입니다.",
    "영유아 자녀는 없습니다.", "신생아를 키우지 않습니다.", "유치원에 다니는 조카를 만납니다.",
    "어린 시절 유치원에서 놀았습니다.", "유치원 교사이며 고등학생 자녀를 키웁니다.",
])
def test_child_mentions_do_not_establish_parenthood(profile):
    assert visit.young_child_candidate(profile) is False


@pytest.mark.parametrize("profile", [
    "영유아 자녀를 키웁니다.", "갓난아이를 양육하고 있습니다.", "신생아를 키웁니다.",
    "유치원에 다니는 딸과 함께 삽니다.", "자녀를 어린이집에 보냅니다.",
    "어린이집 교사이며 갓난아이를 키웁니다.",
    "유치원 교사로 일합니다. 신생아를 키웁니다.",
])
def test_child_mentions_remain_review_candidates(profile):
    p = {"uuid": "invented", "age_band": "30대", "sex": "여자", "province": "서울", "profile": profile}
    groups = visit.memberships([p], {}, ())
    child = [(key, value) for key, value in groups.items() if key[0] == "영유아"]
    assert len(child) == 1 and child[0][0][1] == "영유아·보육 관련 언급 인물(확인 후보)"


@pytest.mark.needs_panel
def test_cards_name_the_groups_that_differ_and_where_they_live():
    everyone = panel.load(addons="off")[0]
    people = panel.sample(everyone, 6000, 1)

    def answer(p):
        if p["age_band"] == "70세 이상":
            return [0.3, 0.6, 0.1]      # more of the minority view
        if p["age_band"] == "19–29세":
            return [0.4, 0.2, 0.4]      # more "don't know"
        return [0.6, 0.3, 0.1]

    v = visit.view(SPEC, people, _answers(people, answer), OPTIONS, None, everyone=everyone, context={})
    kinds = {(c["kind"], c["group"]) for c in v["cards"]}
    assert ("differ", "70세 이상") in kinds and ("unsure", "19–29세") in kinds
    old = next(c for c in v["cards"] if c["group"] == "70세 이상")
    assert old["stat"]["option"] == OPTIONS[1] and old["stat"]["diff_pp"] > old["stat"]["threshold_pp"]
    assert "경로당·노인복지관" in old["venues"] and old["where"]["most"] and sum(old["percent"]) == 100
    assert old["questions"][0] == QUESTION and old["basis"] == "기본 인물 정보"
    assert v["missing"][0]["party"] and "농어민" in v["missing"][0]["who"]  # the policy's own parties come first
    assert v["tests"] == v["groups"] * len(OPTIONS) and "실제 조사 아님" in v["copy_text"]
    # Add-on attributes split answers only when the run attached that add-on.
    assert all(c["basis"] == "기본 인물 정보" for c in v["cards"])


@pytest.mark.needs_panel
def test_no_cards_when_nothing_differs_or_the_run_is_small():
    everyone = panel.load(addons="off")[0]
    flat = lambda p: [0.5, 0.3, 0.2]  # noqa: E731
    people = panel.sample(everyone, 6000, 1)
    v = visit.view(SPEC, people, _answers(people, flat), OPTIONS, None, everyone=everyone, context={})
    assert v["cards"] == [] and "최소 차이" in v["small"] and v["region_note"]
    few = panel.sample(everyone, 150, 1)
    v = visit.view(SPEC, few, _answers(few, flat), OPTIONS, None, everyone=everyone, context={})
    assert v["cards"] == [] and "2,000명" in v["small"] and v["missing"]


@pytest.mark.needs_panel
def test_visit_api(api):  # noqa: F811
    app, codes = api
    a = login(app, codes, "a@x.go.kr")
    sid = a.post("/api/surveys", json={"title": "시내버스", "policy_text": "시내버스 요금을 지원한다. " * 5}, headers=H).json()["id"]
    run = a.post(f"/api/surveys/{sid}/runs", json={"question": QUESTION, "options": OPTIONS}, headers=H).json()["run"]
    assert a.get(f"/api/runs/{run['id']}/visit").status_code == 409  # not finished yet
    drain(app.state.runner)
    got = a.get(f"/api/runs/{run['id']}/visit")
    assert got.status_code == 200 and {"cards", "missing", "method"} <= set(got.json()["visit"])
    assert login(app, codes, "b@x.go.kr").get(f"/api/runs/{run['id']}/visit").status_code == 404
