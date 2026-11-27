import json

import pytest

from pp import jev, jev_panel, segment

POLICY = "1. 추진 배경\n고령화로 도시철도 무임수송 손실이 커지고 있어 제도를 손보려는 것이다.\n2. 주요 내용\n가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.\n"
PERSON = {"uuid": "u1", "name": "김영숙", "sex": "여자", "age": 72, "district": "서울-중랑구", "province": "서울",
          "occupation": "무직", "education_level": "초등학교", "marital_status": "사별", "family_type": "혼자 거주",
          "housing_type": "단독주택", "persona": "김영숙 씨는 매일 지하철로 복지관에 갑니다.", "professional_persona": "",
          "family_persona": "", "cultural_background": ""}


def test_key_from_repo_env(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(jev.config, "REPO_ROOT", tmp_path)
    assert jev.api_key() is None
    (tmp_path / ".env").write_text("OTHER=1\nTYPESAFE_API_KEY=apikey_test\n", encoding="utf-8")
    assert jev.api_key() == "apikey_test"


def test_mock_answers_match_question_types(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    qs = jev_panel.questions(segment.split_segments(POLICY))
    out = jev.evaluate({"policy": POLICY, "person": "x"}, qs)
    assert set(out["answers"]) == set(qs)
    assert out["answers"]["direct"]["type"] == "noul"
    assert out["answers"]["channel"]["choice"] in jev_panel.CHANNELS
    assert out["answers"]["stance"]["legend"]["0"] == jev_panel.STANCE_LEVELS[0]
    again = jev.evaluate({"policy": POLICY, "person": "x"}, qs)
    assert again == out


def test_questions_cover_every_segment():
    segs = segment.split_segments(POLICY)
    qs = jev_panel.questions(segs)
    assert {f"seg_{s['id']}" for s in segs} <= set(qs)
    assert qs["stance"]["criteria"] == jev_panel.STANCE_LEVELS and len(jev_panel.STANCE_LEVELS) == 5


def test_summarize_turns_answers_into_numbers():
    segs = [{"id": "s1", "label": "1. 추진 배경"}]
    answer = {"answers": {
        "stance": {"type": "score", "score": 1.5, "confidence": 0.6,
                   "probabilities": {"0": 0.1, "1": 0.4, "2": 0.4, "3": 0.1, "4": 0.0}},
        "direct": {"type": "noul", "noul": 0.8},
        "comment": {"type": "noul", "noul": 0.25},
        "channel": {"type": "choice", "choice": "senior_center", "confidence": 0.7,
                    "probabilities": {"senior_center": 0.7, "none": 0.3}},
        "seg_s1": {"type": "noul", "noul": 0.35},
    }}
    row = jev_panel.summarize(answer, segs)
    assert row["stance"] == -0.5 and row["stance_probs"] == [0.1, 0.4, 0.4, 0.1, 0.0]
    assert row["reserve"] == pytest.approx(0.9)
    assert row["direct"] == 0.8 and row["comment"] == 0.25 and row["channel"] == "senior_center"
    assert row["segments"] == {"s1": 0.35}


def test_run_jev_panel_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    calls = {"n": 0}
    real = jev.evaluate

    def counting(state, questions, **kw):
        calls["n"] += 1
        return real(state, questions, **kw)

    monkeypatch.setattr(jev, "evaluate", counting)
    people = [{**PERSON, "uuid": f"u{i}", "age": 30 + i} for i in range(6)]
    segs = segment.split_segments(POLICY)
    out = tmp_path / "jev.jsonl"
    first, failures = jev_panel.run_jev_panel(people[:4], "정책", POLICY, segs, out, workers=3)
    assert len(first) == 4 and not failures and calls["n"] == 4
    rows, _ = jev_panel.run_jev_panel(people, "정책", POLICY, segs, out, workers=3)
    assert [r["uuid"] for r in rows] == [p["uuid"] for p in people] and calls["n"] == 6
    assert all(set(r["segments"]) == {s["id"] for s in segs} for r in rows)
    assert len(out.read_text(encoding="utf-8").splitlines()) == 6


def test_http_errors_are_retried_then_raised(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    attempts = {"n": 0}

    def boom(*a, **k):
        attempts["n"] += 1
        raise jev.net.NetError("offline")

    monkeypatch.setattr(jev.net, "post", boom)
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    with pytest.raises(jev.JevError):
        jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, retries=2)
    assert attempts["n"] == 3


def test_occupation_questions_pack_many_per_call(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    mapping = jev_panel.map_occupations_jev([f"직업{i}" for i in range(7)] + ["직업0"], per_call=3)
    assert set(mapping) == {f"직업{i}" for i in range(7)}
    assert all(v in jev_panel.MAJORS for v in mapping.values())
    json.dumps(mapping, ensure_ascii=False)


def test_assign_issues_keeps_only_confident_members(monkeypatch):
    issues = [{"title": "요금 부담", "stance": "우려", "summary": "요금이 오른다", "member_ids": ["r1", "r2"]},
              {"title": "안전", "stance": "기대", "summary": "안전해진다", "member_ids": ["r3"]}]
    reactions = [{"rid": f"r{i}", "reason": f"이유 {i}", "concerns": []} for i in (1, 2, 3, 4)]
    answers = {"이유 1": ("i0", 0.9), "이유 2": ("none", 0.8), "이유 3": ("i1", 0.4), "이유 4": ("i0", 0.6)}

    def fake(state, questions, **kw):
        choice, p = answers[state["reaction"]]
        opts = questions["issue"]["criteria"]
        probs = {o: (p if o == choice else round((1 - p) / (len(opts) - 1), 3)) for o in opts}
        return {"answers": {"issue": {"type": "choice", "choice": choice, "confidence": 0.5, "probabilities": probs}}}

    monkeypatch.setattr(jev, "evaluate", fake)
    new, stats = jev_panel.assign_issues(issues, reactions, workers=2)
    assert [it["title"] for it in new] == ["요금 부담"]
    assert new[0]["member_ids"] == ["r1", "r4"] and new[0]["member_probs"] == {"r1": 0.9, "r4": 0.6}
    assert stats == {"reactions": 4, "llm_assigned": 3, "jev_assigned": 2, "both": 1, "agreement": 1.0, "threshold": 0.5}


def test_usage_is_recorded_per_label(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")

    def fake_post(url, body, headers, timeout=0):
        out = {"answers": {"q": {"type": "noul", "noul": 0.5}}, "usage": {"input_tokens": 1200, "output_tokens": 3}}
        return json.dumps(out).encode("utf-8")

    monkeypatch.setattr(jev.net, "post", fake_post)
    jev.reset_usage()
    for _ in range(3):
        jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, label="panel")
    jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, label="assign")
    used = jev.usage()
    assert used["panel"]["calls"] == 3 and used["panel"]["input_tokens"] == 3600
    assert used["assign"]["calls"] == 1 and used["panel"]["seconds"] >= 0
    assert jev.cost_usd(1_000_000) == 0.042
    jev.reset_usage()
    assert jev.usage() == {}


ISSUES = [{"title": "요금 부담", "summary": "요금이 오른다"}, {"title": "안전", "summary": "안전해진다"}]


def test_extended_questions_cover_positions_issues_methods():
    segs = segment.split_segments(POLICY)
    qs = jev_panel.questions(segs, ISSUES)
    assert {f"pos_{s['id']}" for s in segs} <= set(qs) and {"iss_0", "iss_1", "explain", "understand"} <= set(qs)
    assert {f"m_{k}" for k in jev_panel.METHODS} <= set(qs)
    assert qs["pos_" + segs[0]["id"]]["criteria"] == jev_panel.POSITION_LEVELS
    assert set(qs["explain"]["criteria"]) == {s["id"] for s in segs}
    assert "pos_" + segs[0]["id"] not in jev_panel.questions(segs, extended=False)


def test_summarize_reads_extended_answers():
    segs = [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}]
    base = {"stance": {"type": "score", "score": 2.0, "confidence": 0.5, "probabilities": {"0": 0, "1": 0, "2": 1, "3": 0, "4": 0}},
            "direct": {"type": "noul", "noul": 0.1}, "comment": {"type": "noul", "noul": 0.2},
            "channel": {"type": "choice", "choice": "none", "probabilities": {"none": 1.0}},
            "seg_s1": {"type": "noul", "noul": 0.3}, "seg_s2": {"type": "noul", "noul": 0.4}}
    ext = {"pos_s1": {"type": "score", "score": 0.4, "probabilities": {"0": 0.7, "1": 0.2, "2": 0.1}},
           "pos_s2": {"type": "score", "score": 1.8, "probabilities": {"0": 0.0, "1": 0.2, "2": 0.8}},
           "iss_0": {"type": "noul", "noul": 0.9}, "iss_1": {"type": "noul", "noul": 0.05},
           "m_phone": {"type": "noul", "noul": 0.55},
           "explain": {"type": "choice", "choice": "s2", "probabilities": {"s1": 0.25, "s2": 0.75}},
           "understand": {"type": "noul", "noul": 0.6}}
    row = jev_panel.summarize({"answers": {**base, **ext}}, segs, n_issues=2)
    assert row["positions"] == {"s1": -0.6, "s2": 0.8} and row["pos_oppose"] == {"s1": 0.7, "s2": 0.0}
    assert row["issues"] == {"0": 0.9, "1": 0.05} and row["methods"] == {"phone": 0.55}
    assert row["explain"] == {"s1": 0.25, "s2": 0.75} and row["understand"] == 0.6
    plain = jev_panel.summarize({"answers": base}, segs)
    assert "positions" not in plain and "issues" not in plain


def test_consistency_flags_reasons_that_contradict_the_label(monkeypatch):
    reactions = [{"rid": "r1", "support": 2, "reason": "정말 좋아요"}, {"rid": "r2", "support": 1, "reason": "절대 안 됩니다"},
                 {"rid": "r3", "support": -1, "reason": "부담돼요"}]
    expected = {"정말 좋아요": 3.8, "절대 안 됩니다": 0.2, "부담돼요": 1.2}

    def fake(state, questions, **kw):
        return {"answers": {"stance": {"type": "score", "score": expected[state["statement"]], "probabilities": {}}}}

    monkeypatch.setattr(jev, "evaluate", fake)
    out = jev_panel.check_consistency(reactions, "정책", workers=2)
    assert out["n"] == 3 and out["flagged"] == 1 and out["items"][0]["rid"] == "r2"
    assert out["items"][0]["llm"] == 1 and out["items"][0]["jev"] == -1.8
    assert out["by_rid"]["r3"] == -0.8


def test_score_variants_pairs_the_same_people_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = [{**PERSON, "uuid": f"u{i}", "age": 60 + i} for i in range(3)]
    variants = [{"id": "a1", "text": "[수정안] 저소득층은 계속 무임승차를 받는다."}]
    out = tmp_path / "alternatives.jsonl"
    rows, failures = jev_panel.score_variants(people, "정책", POLICY, variants, out, workers=2)
    assert not failures and sorted((r["uuid"], r["variant"]) for r in rows) == sorted(
        (p["uuid"], v) for p in people for v in ("base", "a1"))
    assert all(len(r["probs"]) == 5 for r in rows)
    calls = {"n": 0}
    real = jev.evaluate
    monkeypatch.setattr(jev, "evaluate", lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
    again, _ = jev_panel.score_variants(people, "정책", POLICY, variants, out, workers=2)
    assert calls["n"] == 0 and len(again) == 6


def test_rate_limiter_spaces_calls_across_threads():
    import threading
    import time as _time
    limiter = jev.RateLimiter(50)  # one call per 20 ms
    stamps = []
    lock = threading.Lock()

    def worker():
        for _ in range(3):
            limiter.wait()
            with lock:
                stamps.append(_time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stamps.sort()
    assert len(stamps) == 12 and stamps[-1] - stamps[0] >= 11 * 0.02 * 0.9
    assert jev.RateLimiter(0).interval == 0


def test_score_questions_asks_every_question_per_person(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = [{**PERSON, "uuid": f"u{i}", "age": 40 + i} for i in range(4)]
    qa = [{"question": "언제부터 적용되나요?"}, {"question": "저도 대상인가요?"}]
    rows = jev_panel.score_questions(people, "정책", POLICY, qa, workers=2)
    assert [r["uuid"] for r in rows] == [p["uuid"] for p in people]
    assert all(set(r["asks"]) == {"0", "1"} and all(0 <= v <= 1 for v in r["asks"].values()) for r in rows)


def test_cache_reuses_answers_keeps_option_order_and_can_be_bypassed(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PP_JEV_CACHE", "1")
    calls = {"n": 0}

    def fake_post(url, body, headers, timeout=0):
        calls["n"] += 1
        assert headers["Authorization"] == "Bearer apikey_test"  # the API key, never the cache key
        return json.dumps({"answers": {"q": {"type": "noul", "noul": 0.5}},
                           "usage": {"input_tokens": 1000}}).encode("utf-8")

    monkeypatch.setattr(jev.net, "post", fake_post)
    jev.reset_usage()
    q = {"q": {"type": "noul", "instructions": "x"}}
    a = jev.evaluate("same state", q, label="t")
    b = jev.evaluate("same state", q, label="t")
    assert a == b and calls["n"] == 1
    jev.evaluate("same state", q, label="t", cache=False)
    jev.evaluate("other state", q, label="t")
    assert calls["n"] == 3
    ab = {"q": {"type": "choice", "instructions": "x", "criteria": {"a": None, "b": None}}}
    ba = {"q": {"type": "choice", "instructions": "x", "criteria": {"b": None, "a": None}}}
    jev.evaluate("s", ab, label="t")
    jev.evaluate("s", ba, label="t")
    assert calls["n"] == 5  # reversed options are a different question, not a cache hit
    used = jev.usage()["t"]
    assert used["calls"] == 5 and used["cached"] == 1 and used["input_tokens"] == 5000
    assert (tmp_path / "jev-cache.sqlite").exists()


SEGS = [{"id": "s1", "label": "가. 기준 연령", "text": "무임승차 기준 연령을 70세로 올린다."},
        {"id": "s2", "label": "나. 예외", "text": "기초연금 수급자는 예외로 한다."}]


def test_check_clarity_scores_every_clause_and_the_document(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    out = jev_panel.check_clarity("정책", POLICY, SEGS, workers=2)
    assert [c["segment_id"] for c in out["clauses"]] == ["s1", "s2"]
    assert all(set(c["values"]) == set(jev_panel.CLARITY) for c in out["clauses"])
    assert all(c["flags"] == sorted((k for k, v in c["values"].items() if v >= 0.5), key=lambda k: -c["values"][k])
               for c in out["clauses"])
    assert [d["key"] for d in out["document"]] == list(jev_panel.DOC_CHECKS)
    assert [i["key"] for i in out["indicators"]] == list(jev_panel.CLARITY)


def test_issue_order_check_averages_both_orders(monkeypatch):
    issues = [{"title": "요금", "summary": "s", "member_ids": ["r1"], "k": 0},
              {"title": "안전", "summary": "s", "member_ids": ["r2"], "k": 1}]
    reactions = [{"rid": f"r{i}", "reason": f"이유 {i}", "concerns": []} for i in (1, 2, 3)]
    # (original order, reversed order) probabilities of the chosen option
    table = {"이유 1": ({"i0": 0.9, "i1": 0.05, "none": 0.05}, {"i0": 0.8, "i1": 0.1, "none": 0.1}),
             "이유 2": ({"i0": 0.1, "i1": 0.45, "none": 0.45}, {"i0": 0.1, "i1": 0.8, "none": 0.1}),
             "이유 3": ({"i0": 0.6, "i1": 0.1, "none": 0.3}, {"i0": 0.2, "i1": 0.1, "none": 0.7})}

    def fake(state, questions, **kw):
        crit = list(questions["issue"]["criteria"])
        probs = table[state["reaction"]][0 if crit[0] == "i0" else 1]
        choice = max(probs, key=probs.get)
        return {"answers": {"issue": {"type": "choice", "choice": choice, "probabilities": probs}}}

    monkeypatch.setattr(jev, "evaluate", fake)
    kept, stats = jev_panel.assign_issues_both_orders(issues, reactions, workers=2)
    assert [(it["title"], it["member_ids"], it["k"]) for it in kept] == [("요금", ["r1"], 0), ("안전", ["r2"], 1)]
    assert kept[1]["member_probs"] == {"r2": 0.625}
    # r2 was below the threshold in the original order alone; r3 passed in the original order but not on average
    assert stats == {"reactions": 3, "same_choice": 2, "agreement": 0.667, "flips": 2, "assigned": 2,
                     "mean_shift": 0.283, "threshold": 0.5}


def test_tag_reactions_returns_every_lens(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    reactions = [{"rid": "r1", "reason": "요금이 부담돼요", "concerns": ["요금"], "hopes": []},
                 {"rid": "r2", "reason": "좋은 정책이에요", "concerns": [], "hopes": ["안전"]}]
    tags = jev_panel.tag_reactions(reactions, "정책", workers=2)
    assert set(tags) == {"r1", "r2"} and all(set(t) == set(jev_panel.LENSES) for t in tags.values())
    assert all(0 <= v <= 1 for t in tags.values() for v in t.values())


def test_batching_and_repeat_checks(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = [{**PERSON, "uuid": f"u{i}", "age": 60 + i} for i in range(4)]
    segs = segment.split_segments(POLICY)
    batched = {p["uuid"]: {"stance": 0.1 * i, "direct": 0.5, "channel": "none"} for i, p in enumerate(people)}
    seen = {"cache": []}
    real = jev.evaluate

    def spy(state, questions, **kw):
        seen["cache"].append(kw.get("cache", True))
        return real(state, questions, **kw)

    monkeypatch.setattr(jev, "evaluate", spy)
    b = jev_panel.check_batching(people, "정책", POLICY, batched, workers=2)
    assert b["n"] == 4 and b["mean_abs_diff"] >= 0 and b["max_abs_diff"] >= b["mean_abs_diff"]
    r = jev_panel.check_repeat(people, "정책", POLICY, segs, [], batched, workers=2)
    assert r["n"] == 4 and 0 <= r["channel_same"] <= 1 and set(r) >= {"stance_mean_abs_diff", "direct_mean_abs_diff"}
    assert seen["cache"][-4:] == [False] * 4  # a repeat must reach the model, not the cache


def test_read_hearing_reads_every_speech(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = {"u1": {**PERSON, "uuid": "u1"}, "u2": {**PERSON, "uuid": "u2", "name": "박철수", "age": 40}}
    turns = [{"round": 0, "speaker": "사회자", "text": "시작합니다."},
             {"round": 1, "speaker": "u1", "text": "반대합니다."},
             {"round": 1, "speaker": "u2", "text": "찬성합니다."},
             {"round": 2, "speaker": "사회자", "text": "반론을 해 주세요."},
             {"round": 2, "speaker": "u1", "text": "조금 양보하겠습니다."}]
    reads = jev_panel.read_hearing("정책", ["요금"], turns, people, workers=2)
    assert [r["index"] for r in reads] == [1, 2, 4] and [r["speaker"] for r in reads] == ["u1", "u2", "u1"]
    assert all(-2 <= r["stance"] <= 2 and set(r["marks"]) == set(jev_panel.TURN_MARKS) for r in reads)


def test_auth_errors_fail_fast(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "api")
    monkeypatch.setenv("TYPESAFE_API_KEY", "apikey_test")
    attempts = {"n": 0}

    def always_401(url, body, headers, timeout=0):
        attempts["n"] += 1
        raise jev.net.HTTPError(401, {}, b"Unauthorized")

    monkeypatch.setattr(jev.net, "post", always_401)
    with pytest.raises(jev.JevError):
        jev.evaluate("state", {"q": {"type": "noul", "instructions": "x"}}, retries=4)
    assert attempts["n"] == 1


def test_rate_limit_wait_follows_the_reset_time(monkeypatch):
    monkeypatch.setattr(jev.time, "time", lambda: 1000.0)
    assert jev._retry_wait({"retry-after": "7"}, 0) == 7.0
    assert jev._retry_wait({"x-upstage-ratelimit-reset-tokens": "1040", "x-upstage-ratelimit-reset-requests": "1010"}, 0) == 41.0
    assert jev._retry_wait({"x-upstage-ratelimit-reset-tokens": "1500"}, 0) == 65.0
    assert jev._retry_wait({}, 2) == 6.0
