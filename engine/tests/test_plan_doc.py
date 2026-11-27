from pp import plan_doc


def test_build_plan_sections_and_verbatim_quotes():
    policy = {"title": "무임승차 연령 조정", "kind": "가상 정책안", "agency": "국토교통부"}
    analysis = {
        "overall": {"n": 300}, "overall_aff": {"n": 80},
        "issues": [{"id": "i1", "title": "요금 부담", "stance": "우려", "n": 40, "share": 0.1, "mean": -1.1,
                    "segments": ["s2", "zz"], "groups": [{"group": "70세 이상"}], "summary": "요약",
                    "quotes": [{"rid": "r3", "uuid": "u3", "text": "버스비도 부담이에요."}]}],
        "outreach": [{"kind": "직업군", "group": "농림어업 숙련 종사자", "n": 12, "direct": 0.8, "oppose": 0.7,
                      "silent": 0.9, "channels": ["경로당"], "member_uuids": ["u1"], "sample_quotes": [],
                      "suggestion": {"method": "방문 간담회", "where": "경로당", "when": "예고 기간 중", "why": "근거"}}],
        "suggestions": [{"title": "단계적 시행", "n": 5, "example": "천천히 올려 주세요.", "member_ids": ["r1"]}],
    }
    segments = [{"id": "s2", "label": "가. 기준 연령 상향"}]
    qa = [{"question": "언제부터인가요?", "answer": "시행 시기를 설명", "issue_id": "i1"}]
    meta = {"created_at": "2026-09-24T01:00:00+00:00"}
    plan = plan_doc.build_plan(policy, analysis, segments, qa, meta)
    assert plan["overview"]["panel"] == "대표 패널 300명 + 영향권 패널 80명"
    assert plan["overview"]["created_at"] == "2026-09-24"
    assert plan["issues"][0]["segments"] == ["가. 기준 연령 상향"]
    assert plan["issues"][0]["quote"] == "버스비도 부담이에요."
    assert plan["outreach"][0]["suggestion"]["method"] == "방문 간담회"
    assert plan["suggestions"][0]["example"] == "천천히 올려 주세요."
    assert plan["qa"] == qa and len(plan["limits"]) >= 4


def test_plan_date_is_korean_local_date():
    assert plan_doc.local_date("2026-09-23T15:50:31+00:00") == "2026-09-24"
    assert plan_doc.local_date("2026-09-23T14:59:59+00:00") == "2026-09-23"


def test_plan_carries_jev_methods_amendments_and_explanation_needs():
    policy = {"title": "무임승차", "kind": "가상 정책안"}
    analysis = {
        "overall": {"n": 300}, "overall_aff": {"n": 100},
        "issues": [{"id": "i1", "title": "요금", "stance": "우려", "n": 40, "share": 0.1, "mean": -1.1, "summary": "s",
                    "segments": [], "groups": [], "quotes": [], "jev_mean": 0.46}],
        "outreach": [{"kind": "직업군", "group": "단순노무", "n": 200, "direct": 0.3, "oppose": 0.6, "silent": 0.8,
                      "channels": [], "suggestion": {"method": "m", "where": "w", "when": "t", "why": "y"},
                      "methods": [{"key": "phone", "label": "10분 전화 인터뷰", "p": 0.55}]}],
        "suggestions": [],
        "jev": {"explain": {"overall": {"s1": 0.2, "s2": 0.7, "s3": 0.1}, "top": "s2",
                            "understand": {"overall": 0.52, "education_level": [
                                {"group": "초등학교", "n": 400, "small": False, "mean": 0.31},
                                {"group": "무학", "n": 12, "small": True, "mean": 0.1}]}}},
        "alternatives": {"n": 1500, "baseline": {"n": 1500}, "items": [
            {"id": "a1", "title": "안내 강화", "text": "[수정안] 안내", "source_title": "안내", "source_n": 5, "source_example": "알려 주세요",
             "n": 1500, "d_favor": 0.01, "d_reserve": -0.01, "d_mean": 0.02, "movers": []},
            {"id": "a2", "title": "저소득 예외", "text": "[수정안] 예외", "source_title": "예외", "source_n": 30, "source_example": "빼 주세요",
             "n": 1500, "d_favor": 0.09, "d_reserve": -0.08, "d_mean": 0.2, "movers": [{"kind": "연령대", "group": "60대", "d_mean": 0.6}]}]},
    }
    segments = [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}, {"id": "s3", "label": "다"}]
    plan = plan_doc.build_plan(policy, analysis, segments, [], {"created_at": "2026-09-24T01:00:00+00:00"})
    assert [a["title"] for a in plan["alternatives"]] == ["저소득 예외", "안내 강화"]
    assert plan["alternatives"][0]["movers"][0]["group"] == "60대"
    assert plan["outreach"][0]["methods"][0]["label"] == "10분 전화 인터뷰"
    assert plan["explain"]["clauses"][:2] == [{"segment_id": "s2", "label": "나", "p": 0.7}, {"segment_id": "s1", "label": "가", "p": 0.2}]
    assert plan["explain"]["understand"] == 0.52 and plan["explain"]["hardest"] == {"group": "초등학교", "mean": 0.31}
    assert plan["issues"][0]["jev_mean"] == 0.46
    assert any("날짜" in line for line in plan["limits"])


def test_plan_lists_unclear_clauses_and_missing_notice_items():
    policy = {"title": "무임승차", "kind": "가상 정책안"}
    analysis = {"overall": {"n": 300}, "overall_aff": {"n": 100}, "issues": [], "outreach": [], "suggestions": []}
    segments = [{"id": "s1", "label": "가. 기준 연령"}, {"id": "s2", "label": "나. 예외"}]
    clarity = {"available": True, "threshold": 0.5,
               "indicators": [{"key": "vague_who", "label": "대상 모호"}, {"key": "jargon", "label": "어려운 용어"}],
               "clauses": [{"segment_id": "s1", "values": {"vague_who": 0.8, "jargon": 0.6}, "flags": ["vague_who", "jargon"]},
                           {"segment_id": "s2", "values": {"vague_who": 0.2, "jargon": 0.1}, "flags": []}],
               "document": [{"key": "cost", "label": "재정·비용 추계", "p": 0.2}, {"key": "when", "label": "시행 시기", "p": 0.9}]}
    plan = plan_doc.build_plan(policy, analysis, segments, [], {"created_at": "2026-09-24T01:00:00+00:00"}, clarity=clarity)
    assert plan["clarity"]["clauses"] == [{"segment_id": "s1", "label": "가. 기준 연령",
                                            "flags": [{"key": "vague_who", "label": "대상 모호", "p": 0.8},
                                                      {"key": "jargon", "label": "어려운 용어", "p": 0.6}]}]
    assert plan["clarity"]["missing"] == [{"key": "cost", "label": "재정·비용 추계", "p": 0.2}]
    assert plan_doc.build_plan(policy, analysis, segments, [], {"created_at": "2026-09-24T01:00:00+00:00"})["clarity"] is None
