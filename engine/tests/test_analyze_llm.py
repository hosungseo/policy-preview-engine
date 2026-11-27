import pytest

from pp import analyze_llm as al
from pp import config, llm
from pp import mock  # noqa: F401  (register mock handlers before tests override them)


def rx(i, support=-1, suggestion="", seg=None):
    return {"rid": f"r{i}", "uuid": f"u{i}", "support": support, "reason": f"이유 문장 {i}번입니다.",
            "concerns": ["요금"], "suggestion": suggestion, "segment_id": seg}


def people_for(rs):
    return {r["uuid"]: {"uuid": r["uuid"], "age": 20 + (int(r["uuid"][1:]) * 9) % 60, "province": "서울",
                        "occupation_major": "사무 종사자"} for r in rs}


def test_validate_clusters_drops_unknown_and_duplicates():
    data = {"issues": [
        {"title": " 요금 부담 ", "stance": "우려", "summary": "s", "member_ids": ["r1", "r2", "zz"]},
        {"title": "안전", "stance": "없는값", "member_ids": ["r2", "r3"]},
        {"title": "", "member_ids": ["r4"]},
        {"title": "빈 묶음", "member_ids": ["nope"]},
    ]}
    assert al.validate_clusters(data, {"r1", "r2", "r3", "r4"}) == [
        {"title": "요금 부담", "stance": "우려", "summary": "s", "member_ids": ["r1", "r2"]},
        {"title": "안전", "stance": "혼재", "summary": "", "member_ids": ["r3"]},
    ]
    with pytest.raises(ValueError):
        al.validate_clusters({"issues": []}, {"r1"})


def test_cluster_and_enrich_issues(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    rs = [rx(i, support=(i % 5) - 2, seg="s1" if i % 2 else None) for i in range(1, 13)]
    issues = al.enrich_issues(al.cluster_issues(rs, "테스트 정책"), rs, people_for(rs))
    assert [it["id"] for it in issues] == ["i1", "i2", "i3"]
    assert abs(sum(it["share"] for it in issues) - 1.0) < 0.01
    reasons = {r["rid"]: r["reason"] for r in rs}
    assert all(q["text"] == reasons[q["rid"]] for it in issues for q in it["quotes"])
    assert issues[0]["segments"] == ["s1"]



def test_enrich_prefers_confident_members_as_quotes():
    rs = [rx(i, support=0) for i in range(1, 7)]
    issue = {"title": "요금 부담", "stance": "우려", "summary": "s", "member_ids": [r["rid"] for r in rs],
             "member_probs": {"r1": 0.55, "r2": 0.6, "r3": 0.9, "r4": 0.95, "r5": 0.7, "r6": 0.52}}
    [out] = al.enrich_issues([issue], rs, people_for(rs))
    assert [q["rid"] for q in out["quotes"]] == ["r4", "r3", "r5"]
    assert out["member_probs"]["r4"] == 0.95

def test_cluster_suggestions_small_and_large(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    few = [rx(i, suggestion=f"제안 {i}") for i in range(1, 4)] + [rx(9)]
    assert [s["example"] for s in al.cluster_suggestions(few, "정책")] == ["제안 1", "제안 2", "제안 3"]
    many = [rx(i, suggestion=f"제안 {i}") for i in range(1, 10)]
    big = al.cluster_suggestions(many, "정책")
    assert big and all(s["example"] in {r["suggestion"] for r in many} for s in big)
    assert sum(s["n"] for s in big) == 9


def test_map_occupations_uses_cache_and_falls_back(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    calls = {"n": 0}

    def handler(system, prompt):
        calls["n"] += 1
        return {"map": {"택시 운전원": "장치·기계 조작 및 조립 종사자", "무직": "없는 분류"}}

    monkeypatch.setitem(llm.MOCK, "occupation", handler)
    out = al.map_occupations(["택시 운전원", "무직", "택시 운전원"])
    assert out == {"택시 운전원": "장치·기계 조작 및 조립 종사자", "무직": "무직·기타"}
    assert config.occupation_cache(mock=True).exists()
    al.map_occupations(["무직"])
    assert calls["n"] == 1


def test_outreach_text_merges_and_requires_all_groups(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    rs = {f"u{i}": rx(i, support=-2) for i in range(1, 7)}
    cands = [{"kind": "직업군", "group": "농림어업 숙련 종사자", "n": 6, "direct": 1.0, "oppose": 1.0,
              "silent": 1.0, "score": 1.0, "channels": ["경로당"], "member_uuids": list(rs)}]
    out = al.outreach_text(cands, rs, "정책")
    assert out[0]["suggestion"]["method"] == "MOCK 방문 간담회"
    assert out[0]["sample_quotes"] == [rs["u1"]["reason"], rs["u2"]["reason"]]
    monkeypatch.setitem(llm.MOCK, "outreach", lambda s, p: {"items": []})
    with pytest.raises(llm.LLMError):
        al.outreach_text(cands, rs, "정책")



def test_outreach_quotes_are_distinct_and_fall_back_to_most_reserved(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    rs = {"u1": rx(1, support=0), "u2": rx(2, support=2), "u3": {**rx(3, support=1), "concerns": ["요금", "안전"]},
          "u4": rx(4, support=1)}
    base = {"n": 40, "direct": 0.5, "oppose": 0.3, "silent": 0.8, "score": 0.1, "channels": []}
    cands = [{**base, "kind": "직업군", "group": "가 집단", "member_uuids": ["u1", "u2", "u3"]},
             {**base, "kind": "가구", "group": "나 집단", "member_uuids": ["u1", "u3", "u4"]}]
    out = al.outreach_text(cands, rs, "정책")
    assert out[0]["sample_quotes"] == [rs["u1"]["reason"], rs["u3"]["reason"]] and out[0]["sample_uuids"] == ["u1", "u3"]
    assert out[1]["sample_quotes"] == [rs["u4"]["reason"]] and out[1]["sample_uuids"] == ["u4"]

def test_plan_qa_filters_unknown_issue_ids(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    issues = [{"id": "i1", "title": "요금", "summary": "요약"}, {"id": "i2", "title": "안전", "summary": "요약"}]
    qa = al.plan_qa(issues, "정책")
    assert qa and all(q["issue_id"] in {"i1", "i2"} for q in qa)
    monkeypatch.setitem(llm.MOCK, "qa", lambda s, p: {"items": [{"question": "질문", "answer": "답", "issue_id": "i9"}]})
    with pytest.raises(llm.LLMError):
        al.plan_qa(issues, "정책")


def test_draft_amendments_keeps_sources_verbatim(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    suggestions = [{"title": "저소득층 예외", "n": 30, "example": "기초연금 못 받는 저소득층도 빼 주세요."},
                   {"title": "버스 지원 확대", "n": 20, "example": "시골 버스도 지원해 주세요."},
                   {"title": "안내 강화", "n": 5, "example": "미리 알려 주세요."}]
    segments = [{"id": "s1", "label": "가. 기준 연령"}, {"id": "s2", "label": "나. 버스 지원"}]
    out = al.draft_amendments(suggestions, "무임승차 정책", "정책 본문", segments, k=2)
    assert [a["id"] for a in out] == ["a1", "a2"]
    assert [a["source_example"] for a in out] == [suggestions[0]["example"], suggestions[1]["example"]]
    assert all(a["text"].startswith("[수정안]") and a["segment_id"] in {"s1", "s2", None} for a in out)
    monkeypatch.setitem(llm.MOCK, "amend", lambda s, p: {"items": [{"source": "c9", "title": "x", "text": "y"}]})
    with pytest.raises(llm.LLMError):
        al.draft_amendments(suggestions, "무임승차 정책", "정책 본문", segments, k=2)
    assert al.draft_amendments([], "정책", "본문", segments) == []
