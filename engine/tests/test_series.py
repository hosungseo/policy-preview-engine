import json

import pytest

from pp import series

PERSON = {"name": "김영숙", "sex": "여자", "age": 74, "district": "경북-안동시", "province": "경상북",
          "occupation": "곡물 재배자", "education_level": "초등학교", "marital_status": "사별",
          "family_type": "혼자 거주", "housing_type": "단독주택", "persona": "김영숙 씨는 농부입니다.",
          "professional_persona": "", "family_persona": "", "cultural_background": ""}
TEXTS = ["주요 내용\n□ 첫째 조치에 관한 설명입니다\n○ 세부 내용\n□ 둘째 조치에 관한 설명입니다",
         "□ 공급을 늘리는 조치입니다\n□ 금융을 지원하는 조치입니다",
         "□ 규제지역을 넓히는 조치입니다\n○ 세부\n□ 거래를 점검하는 조치입니다"]


def _series(tmp_path):
    base = tmp_path / "series"
    (base / "official").mkdir(parents=True)
    (base / "regulated_areas.json").write_text(json.dumps({"periods": [
        {"from": "2023-01-05", "areas": ["서울-중구"], "partial": [], "source": "https://example.org/a"}]}),
        encoding="utf-8")
    (base / "official" / "tenure.json").write_text(json.dumps({
        "year": 2024, "survey": "주거실태조사", "unit": "가구", "publisher": "국토교통부",
        "source": "https://example.org/t", "own": {"서울": 0.43}}, ensure_ascii=False), encoding="utf-8")
    measures = [{"id": f"m{i}", "date": f"2025-0{i + 6}-01", "short": f"{i + 6}·1", "title": f"대책 {i}",
                 "agency": "국토교통부", "text": t, "summary": f"요약 {i}",
                 "source": {"url": "https://example.org/m", "note": "원문"}} for i, t in enumerate(TEXTS)]
    path = base / "test.json"
    path.write_text(json.dumps({"id": "test", "title": "시험 시리즈", "panel": {"n": 60, "seed": 7},
                                "regulated": "regulated_areas.json", "official_tenure": "official/tenure.json",
                                "measures": measures}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def mock_env(persona_db, tmp_path, monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    monkeypatch.setenv("PP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("PP_WEB_SERIES_DIR", str(tmp_path / "pub"))
    monkeypatch.setenv("PP_WEB_DEV_SERIES_DIR", str(tmp_path / "dev"))
    return tmp_path


def test_state_adds_earlier_measures_only_when_there_are_some():
    m = {"title": "대책", "date": "2025-06-27", "text": "□ 내용"}
    assert "earlier_measures" not in series.measure_state(m, PERSON, [])
    assert series.measure_state(m, PERSON, ["앞선 대책"])["earlier_measures"] == ["앞선 대책"]


def test_earlier_summaries_in_date_order():
    ms = [{"date": "2025-06-27", "short": "6·27", "title": "가", "summary": "ㄱ"},
          {"date": "2025-09-07", "short": "9·7", "title": "나", "summary": "ㄴ"},
          {"date": "2025-10-15", "short": "10·15", "title": "다", "summary": "ㄷ"}]
    assert series.earlier_summaries(ms, 2) == ["2025-06-27 6·27 가: ㄱ", "2025-09-07 9·7 나: ㄴ"]
    assert series.earlier_summaries(ms, 0) == []


def test_load_series_rejects_measures_out_of_order(tmp_path):
    path = _series(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["measures"].reverse()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError):
        series.load_series(path)


def test_mock_run_exports_a_valid_dev_bundle_and_resumes_for_free(mock_env):
    path = _series(mock_env)
    dest = series.SeriesRun(path, workers=4).run()
    assert dest.parent == mock_env / "dev"  # mock results never reach the public folder
    text = dest.read_text(encoding="utf-8")
    bundle = json.loads(text)
    assert [m["id"] for m in bundle["measures"]] == ["m0", "m1", "m2"]
    assert bundle["measures"][0]["effect"]["overall"]["diff"] == 0.0  # nothing earlier: one request, one answer
    assert bundle["panel"]["n"] == 60 and '"uuid"' not in text
    meta_path = mock_env / "runs" / "series-test" / "meta.json"

    def calls():
        usage = json.loads(meta_path.read_text(encoding="utf-8"))["jev_usage"]
        return sum(u["calls"] for stage in usage.values() for u in stage.values())

    before = calls()
    assert before == 60 + 3 * 2 * 60
    series.SeriesRun(path, workers=4).run()
    assert calls() == before


def test_subsample_keeps_size_and_strata():
    from collections import Counter

    from pp import config
    people = [{"uuid": f"u{i}", "province": "서울" if i % 3 else "부산", "age": 20 + (i % 60),
               "sex": "남자" if i % 2 else "여자"} for i in range(1000)]
    half = series.subsample(people, 500, seed=1)
    assert len(half) == 500 and len({p["uuid"] for p in half}) == 500
    key = lambda p: (p["province"], config.age_band(p["age"]), p["sex"])  # noqa: E731
    full, part = Counter(map(key, people)), Counter(map(key, half))
    assert all(abs(part[k] - full[k] / 2) <= 1 for k in full)
    assert series.subsample(people, 500, seed=1) == half


def test_housing_run_uses_assigned_tenure_and_adds_the_block(mock_env, monkeypatch):
    path = _series(mock_env)
    series.SeriesRun(path, tag="base", workers=4).run(export=False)
    monkeypatch.setattr(series.housing_context, "assign", lambda p, seed=2026: {
        "tenure": "jeonse" if int(p["uuid"][1:]) % 2 else "own", "probs": {}, "multi_home": False})
    monkeypatch.setattr(series.housing_context, "housing_block", lambda p, a, mid, market: f"주거 정보: {a['tenure']} {mid}")
    monkeypatch.setattr(series.housing_context, "load_market", lambda: {})
    seen = []
    real = series.jev.evaluate
    monkeypatch.setattr(series.jev, "evaluate", lambda state, qs, **kw: (seen.append(state), real(state, qs, **kw))[1])
    dest = series.SeriesRun(path, n=30, tag="ctx", workers=4, housing=True, panel_from="series-test-base",
                            export_id="test-ctx").run()
    assert dest.name == "test-ctx.json" and dest.parent == mock_env / "dev"
    bundle = json.loads(dest.read_text(encoding="utf-8"))
    assert bundle["panel"]["n"] == 30 and bundle["housing_context"]["tenure"] == "assigned"
    base = {p["uuid"] for p in json.loads((mock_env / "runs" / "series-test-base" / "panel.json").read_text(encoding="utf-8"))["people"]}
    ctx = [p["uuid"] for p in json.loads((mock_env / "runs" / "series-test-ctx" / "panel.json").read_text(encoding="utf-8"))["people"]]
    assert set(ctx) <= base and len(ctx) == 30
    assert seen and all("housing" in s and "person" in s for s in seen)  # the tenure question is not asked
    groups = {g["group"]: g["n"] for g in bundle["measures"][0]["conditions"]["alone"]["groups"]["tenure"]}
    assert groups["자가"] + groups["전세"] == 30 and groups["월세"] == 0
    assert bundle["kind_label"]["tenure"] == "점유 형태(배정)"
    m = bundle["measures"][1]
    assert [g["n"] for g in m["conditions"]["alone"]["groups"]["price_band"]] == [30]  # no market data: one band
    assert m["housing_examples"][0]["text"] == f"주거 정보: own {m['id']}"
    ba = m["before_after"]
    assert ba["overall"]["n"] == 30 and len(ba["overall"]["favor"]) == 2
    assert sum(g["n"] for g in ba["groups"]["tenure"]) == 30
    before = bundle["housing_context"]["tenure_before"]  # the base run's Jev estimate for the same people
    assert set(before) == {"own", "jeonse", "monthly", "other"} and abs(sum(before.values()) - 1) < 0.01


def test_subtitle_counts_the_panel(mock_env):
    path = _series(mock_env)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["subtitle"] = "같은 합성 인물 {n}에게 물은 결과"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    bundle = json.loads(series.SeriesRun(path, workers=4).run().read_text(encoding="utf-8"))
    assert bundle["subtitle"] == "같은 합성 인물 60명에게 물은 결과"
    assert series.people_ko(20000) == "2만 명" and series.people_ko(10000) == "1만 명" and series.people_ko(2500) == "2,500명"
