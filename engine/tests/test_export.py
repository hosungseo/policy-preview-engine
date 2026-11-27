import copy
import json

import pytest

from pp import export

POLICY_TEXT = "가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.\n"


def bundle(provider="cli"):
    return {
        "id": "demo", "title": "데모", "kind": "가상 정책안", "agency": "", "source": {},
        "policy_text": POLICY_TEXT, "segments": [], "population": {}, "panel": {},
        "personas": [{"uuid": "u1", "panel": "rep", "similar": ["u2"]}, {"uuid": "u2", "panel": "aff", "similar": []}],
        "reactions": [
            {"rid": "r1", "uuid": "u1", "support": -1, "reason": "부담돼요.", "suggestion": "천천히요.",
             "trigger_quote": "기준 연령을 단계적으로", "quote_verified": True},
            {"rid": "r2", "uuid": "u2", "support": 1, "reason": "찬성합니다.", "suggestion": "",
             "trigger_quote": "없는 문구", "quote_verified": False},
        ],
        "analysis": {
            "overall": {"n": 1},
            "issues": [{"id": "i1", "title": "부담", "member_ids": ["r1"], "quotes": [{"rid": "r1", "text": "부담돼요."}]}],
            "outreach": [{"group": "g", "sample_quotes": ["부담돼요."]}],
            "suggestions": [{"title": "t", "n": 1, "example": "천천히요."}],
        },
        "hearing": {"participants": ["u1"], "turns": [{"speaker": "사회자"}, {"speaker": "u1"}]},
        "plan": {"issues": [{"title": "t", "quote": "부담돼요."}], "suggestions": [{"example": "천천히요."}]},
        "meta": {"provider": provider, "created_at": "2026-09-24T00:00:00+00:00",
                 "stages": [{"name": "react", "seconds": 10.0}]},
    }


def test_valid_bundle_passes():
    assert export.validate_bundle(bundle()) == []


@pytest.mark.parametrize("mutate, needle", [
    (lambda b: b["analysis"]["issues"][0]["quotes"][0].update(text="다듬은 문장"), "not verbatim"),
    (lambda b: b["analysis"]["issues"][0]["member_ids"].append("r9"), "unknown member"),
    (lambda b: b["plan"]["issues"][0].update(quote="지어낸 말"), "plan issue quote"),
    (lambda b: b["hearing"]["turns"].append({"speaker": "u9"}), "unknown speaker"),
    (lambda b: b["personas"][0]["similar"].append("u9"), "similar"),
    (lambda b: b["reactions"][0].update(trigger_quote="없는 인용문입니다"), "verified quote"),
    (lambda b: b["analysis"]["overall"].update(n=2), "overall n"),
    (lambda b: b["analysis"].update(alternatives={"items": [{"title": "x", "source_example": "지어낸 제안"}]}),
     "amendment source"),
    (lambda b: b["reactions"][0].update(lenses=["no_such_lens"]), "unknown lens"),
    (lambda b: b["hearing"].update(reads=[{"index": 0, "speaker": "사회자"}]), "hearing read"),
])
def test_validator_catches_defects(mutate, needle):
    b = copy.deepcopy(bundle())
    mutate(b)
    assert any(needle in e for e in export.validate_bundle(b))


def test_mock_is_refused_publicly_and_goes_to_dev_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_WEB_RUNS_DIR", str(tmp_path / "public"))
    monkeypatch.setenv("PP_WEB_DEV_RUNS_DIR", str(tmp_path / "dev"))
    with pytest.raises(export.ExportError):
        export.write(bundle("mock"))
    dest = export.write(bundle("mock"), allow_mock=True)
    assert dest == tmp_path / "dev" / "demo.json"
    index = json.loads((tmp_path / "dev" / "index.json").read_text(encoding="utf-8"))
    assert index[0]["id"] == "demo" and index[0]["n_rep"] == 1 and index[0]["seconds"] == 10.0
    real = export.write(bundle("cli"))
    assert real == tmp_path / "public" / "demo.json"


def test_assemble_adds_consistency_and_person_jev_details(tmp_path):
    files = {
        "policy.json": {"id": "d", "title": "t", "kind": "k", "text": POLICY_TEXT},
        "segments.json": [{"id": "s1", "label": "가"}, {"id": "s2", "label": "나"}], "panel.json": {},
        "personas.json": [{"uuid": "u1", "panel": "rep", "sex": "남자", "age": 70, "province": "서울", "district": "종로구",
                           "occupation": "무직", "education_level": "초등학교", "marital_status": "기혼",
                           "family_type": "배우자와 거주", "housing_type": "아파트"}],
        "reactions.json": [{"rid": "r1", "uuid": "u1", "support": 1, "reason": "좋아요"}],
        "analysis.json": {"consistency": {"threshold": 1.5, "by_rid": {"r1": -1.2}}},
        "hearing.json": {}, "plan.json": {}, "meta.json": {},
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    row = {"uuid": "u1", "stance": 0.2, "reserve": 0.5, "direct": 0.4, "comment": 0.1, "understand": 0.3,
           "pos_oppose": {"s1": 0.2, "s2": 0.6}, "methods": {"phone": 0.5, "local_visit": 0.7}}
    (tmp_path / "jev.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    b = export.assemble(tmp_path)
    assert b["reactions"][0]["jev_read"] == -1.2 and b["reactions"][0]["flagged"] is True
    j = b["personas"][0]["jev"]
    assert j["oppose_most"] == {"segment_id": "s2", "p": 0.6} and j["understand"] == 0.3
    assert j["best_method"] == {"key": "local_visit", "label": "경로당·마을 모임 방문 청취", "p": 0.7}


def test_assemble_adds_clarity_lenses_and_hearing_reads(tmp_path):
    files = {
        "policy.json": {"id": "d", "title": "t", "kind": "k", "text": POLICY_TEXT},
        "segments.json": [{"id": "s1", "label": "가"}], "panel.json": {}, "personas.json": [],
        "reactions.json": [{"rid": "r1", "uuid": "u1", "support": 1, "reason": "좋아요"},
                           {"rid": "r2", "uuid": "u2", "support": -1, "reason": "부담돼요"}],
        "analysis.json": {}, "plan.json": {}, "meta.json": {},
        "hearing.json": {"participants": ["u1"], "turns": [{"round": 0, "speaker": "사회자", "text": "시작"},
                                                           {"round": 1, "speaker": "u1", "text": "찬성"}]},
        "clarity.json": {"available": True, "clauses": [{"segment_id": "s1", "values": {}, "flags": []}]},
        "review.json": {"available": True, "lenses": {"r1": {"welcome": 0.9, "cost": 0.2},
                                                      "r2": {"cost": 0.7, "trust": 0.55, "welcome": 0.1}}},
        "debrief.json": {"available": True, "reads": [{"index": 1, "round": 1, "speaker": "u1", "stance": 1.0, "marks": {}}],
                         "participants": [{"uuid": "u1", "stances": {"1": 1.0}, "change": 0.0}], "movers": [], "counts": {}},
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    b = export.assemble(tmp_path)
    assert b["clarity"]["clauses"][0]["segment_id"] == "s1"
    assert b["reactions"][0]["lenses"] == ["welcome"] and b["reactions"][1]["lenses"] == ["cost", "trust"]
    assert b["hearing"]["reads"][0]["index"] == 1 and b["hearing"]["trajectories"]["participants"][0]["uuid"] == "u1"
