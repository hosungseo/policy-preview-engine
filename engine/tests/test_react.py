import pytest

from pp import llm, react, segment

POLICY = "1. 추진 배경\n고령화로 도시철도 무임수송 손실이 커지고 있어 제도를 손보려는 것이다.\n2. 주요 내용\n가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.\n"


def good(**over):
    base = {"support": "-1", "impact": "직접적", "trigger_quote": "무임승차 기준 연령", "reason": "저는 매일 지하철을 타요.",
            "concerns": ["교통비", "", "생활비", "병원", "extra"], "hopes": "없음", "suggestion": None,
            "would_comment": "false", "channel": "경로당"}
    base.update(over)
    return base


def test_normalize_reaction_coerces_types():
    r = react.normalize_reaction(good())
    assert r["support"] == -1 and r["impact"] == "직접"
    assert r["concerns"] == ["교통비", "생활비", "병원"]
    assert r["hopes"] == [] and r["suggestion"] == "" and r["would_comment"] is False


@pytest.mark.parametrize("bad", [
    {"support": 5}, {"support": "많이"}, {"impact": "모름"}, {"reason": "네"},
])
def test_normalize_reaction_rejects(bad):
    with pytest.raises(ValueError):
        react.normalize_reaction(good(**bad))


def test_verify_quotes_marks_segments():
    segs = segment.split_segments(POLICY)
    rs = [{"trigger_quote": "기준 연령을  단계적으로"}, {"trigger_quote": "정책에 없는 문구입니다"}]
    assert react.verify_quotes(rs, POLICY, segs) == 1
    assert rs[0]["quote_verified"] is True and rs[0]["segment_id"] == "s2"
    start, end = rs[0]["quote_span"]
    assert POLICY[start:end] == "기준 연령을 단계적으로"
    assert rs[1]["quote_verified"] is False and rs[1]["segment_id"] is None and rs[1]["quote_span"] is None


def test_run_reactions_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    calls = {"n": 0}
    from pp import mock  # noqa: F401  registers the react handler
    original = llm.MOCK["react"]

    def counting(system, prompt):
        calls["n"] += 1
        return original(system, prompt)

    monkeypatch.setitem(llm.MOCK, "react", counting)
    people = [{"uuid": f"u{i}", "name": "", "sex": "남자", "age": 30 + i, "district": "서울-중구", "province": "서울",
               "occupation": "사무 보조원", "education_level": "고등학교", "marital_status": "미혼",
               "family_type": "혼자 거주", "housing_type": "아파트", "persona": "", "professional_persona": "",
               "family_persona": "", "cultural_background": ""} for i in range(5)]
    out = tmp_path / "reactions.jsonl"
    first, failures = react.run_reactions(people[:3], POLICY, out, workers=2)
    assert len(first) == 3 and not failures and calls["n"] == 3
    second, _ = react.run_reactions(people, POLICY, out, workers=2)
    assert [r["uuid"] for r in second] == [p["uuid"] for p in people]
    assert calls["n"] == 5
