import json
import threading
import urllib.error
import urllib.request

import pytest

from pp import config, panel_provider


def test_representative_panel_is_stratified_and_repeatable(persona_db):
    one = panel_provider.provide({"policy_text": "", "n": 34})
    two = panel_provider.provide({"policy_text": "", "n": 34})
    other = panel_provider.provide({"policy_text": "", "n": 34, "seed": 7})
    assert [p["uuid"] for p in one["people"]] == [p["uuid"] for p in two["people"]]
    assert [p["uuid"] for p in one["people"]] != [p["uuid"] for p in other["people"]]
    assert one["counts"] == {"requested": 34, "returned": 34, "eligible": 170, "representative": 34,
                             "affected_requested": 0, "affected_found": 0}
    assert len({p["uuid"] for p in one["people"]}) == 34
    # asking for more than there are returns everyone once, in the proportions of the database
    everyone = panel_provider.provide({"policy_text": "", "n": 500})
    provinces = [p["province"] for p in everyone["people"]]
    assert everyone["counts"]["returned"] == 170 and len(set(provinces)) == 17
    assert all(provinces.count(name) == 10 for name in set(provinces))


def test_output_says_synthetic_and_carries_agent_fields(persona_db):
    out = panel_provider.provide({"policy_text": "", "n": 3})
    assert out["schema"] == "pp.panel/1" and out["synthetic"] is True
    assert "합성 인물" in out["notice"] and "실제 여론이 아닙니다" in out["notice"]
    assert out["source"]["license"] == "CC BY 4.0" and out["source"]["population"] == 170
    person = out["people"][0]
    assert person["kind"] == "representative" and person["found_by"] == []
    assert person["province"] in config.PROVINCE_DISPLAY.values()
    assert person["label"] == " · ".join([person["age_band"], person["sex"], person["province"], person["occupation"]])
    agent = person["agent"]
    assert agent["persona"].startswith("[합성 인물] ") and len(agent["persona"]) <= 800
    assert agent["name"].endswith("#" + person["uuid"][-6:])
    # the provider never invents a stance or an activity level
    assert agent["stance"] == panel_provider.NEUTRAL_STANCE and agent["stance_basis"] == "none"
    assert agent["activity"] == 0.5 and agent["activity_basis"] == "default"
    assert "policy_text" not in out["request"] and out["request"]["policy_chars"] == 0


def test_affected_people_come_from_occupations_named_in_the_policy(persona_db):
    text = "택시 운전원의 운행 기록을 공개한다. 간호사 배치 기준도 고친다."
    out = panel_provider.provide({"policy_text": text, "n": 20, "affected": 8})
    assert out["affected_search"]["occupations_in_text"] == ["택시 운전원", "간호사"]
    affected = [p for p in out["people"] if p["kind"] == "affected"]
    assert len(affected) == 8 and out["counts"]["affected_found"] == 8
    assert {p["occupation"] for p in affected} <= {"택시 운전원", "간호사"}
    assert all(p["found_by"] == ["filter"] for p in affected)
    assert out["counts"]["representative"] == 12 and out["counts"]["returned"] == 20
    assert len({p["uuid"] for p in out["people"]}) == 20


def test_affected_people_from_caller_keywords_and_occupations(persona_db):
    out = panel_provider.provide({"policy_text": "", "n": 10, "affected": 4, "keywords": ["지하철로", "버스"],
                                  "occupations": ["요양보호사"]})
    search = out["affected_search"]
    assert search["keywords_used"] == ["지하철로"] and search["keywords_too_short"] == ["버스"]
    assert search["occupations_used"] == ["요양보호사"]
    assert search["channels"]["fts"] > 0 and search["channels"]["filter"] > 0
    assert out["counts"]["affected_found"] == 4


def test_no_search_channel_fills_with_representative_people(persona_db):
    out = panel_provider.provide({"policy_text": "아무 직업도 나오지 않는 글", "n": 10, "affected": 4})
    assert out["counts"]["affected_found"] == 0 and out["counts"]["representative"] == 10
    assert out["counts"]["returned"] == 10 and len({p["uuid"] for p in out["people"]}) == 10


def test_demographic_limits_apply_to_both_parts(persona_db):
    out = panel_provider.provide({"policy_text": "간호사", "n": 6, "affected": 2, "provinces": ["경상북도", "서울"],
                                  "age_min": 30, "sex": "여자"})
    assert out["request"]["provinces"] == ["경상북", "서울"]
    assert out["people"] and all(p["province"] in ("경북", "서울") and p["age"] >= 30 and p["sex"] == "여자"
                                 for p in out["people"])
    assert out["counts"]["returned"] <= out["counts"]["eligible"]


@pytest.mark.parametrize("raw, message", [
    ({"policy_text": "", "n": 0}, "n must be between"),
    ({"policy_text": "", "n": 5, "affected": 6}, "affected must be between"),
    ({"policy_text": "", "n": "5"}, "n must be an integer"),
    ({"policy_text": "", "n": 5, "provinces": ["없는도"]}, "unknown province"),
    ({"policy_text": "", "n": 5, "age_min": 60, "age_max": 30}, "age_min is greater"),
    ({"policy_text": "", "n": 5, "sex": "기타"}, "sex must be"),
    ({"policy_text": "", "n": 5, "stratify": "x"}, "unknown request keys"),
    ({"policy_text": "", "n": 5, "keywords": "택시"}, "keywords must be a list"),
    ({"policy_text": "", "n": 5, "age_min": 120}, "no one in the database"),
])
def test_bad_requests_are_rejected(persona_db, raw, message):
    with pytest.raises(panel_provider.PanelRequestError, match=message):
        panel_provider.provide(raw)


def test_missing_database_is_a_clear_error(tmp_path, capsys):
    missing = tmp_path / "nowhere" / "persona.db"
    with pytest.raises(config.DataMissing, match="persona DB not found"):
        panel_provider.provide({"policy_text": "", "n": 3}, missing)


def test_database_is_opened_read_only(persona_db):
    provider = panel_provider.Provider()
    try:
        with pytest.raises(Exception, match="readonly"):
            provider.conn.execute("DELETE FROM persona")
    finally:
        provider.close()
