"""Outputs carry their source and terms; group names and proxies are not read as eligibility, ability or amounts."""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from pp import attribution, config, life_context
from pp import life_history as lh
from ppservice.survey import aggregate, lint, visit

ENGINE = Path(__file__).resolve().parents[1]
REV = "ada0f5b53a38bb5a30cce09358adde883c1ab63a"
OPTIONS = ["찬성", "반대", "잘 모르겠다"]
SPEC = {"title": "합성 예시", "policy_text": "가상의 생활 지원 정책을 시행한다.", "question": "이 정책에 찬성하십니까?"}


# --- attribution block ---------------------------------------------------------------------------------------------

def test_build_names_licence_revision_and_changes():
    block = attribution.build({"source_revision": REV, "revision_status": "resolved"},
                              stats=["2025 가계금융복지조사"], extra=[attribution.BOUNDARIES])
    assert attribution.validate(block) == []
    roles = [s["role"] for s in block["sources"]]
    assert roles == ["synthetic_personas", "public_statistics", "boundaries", "generated"]
    persona = block["sources"][0]
    assert persona["license"] == "CC BY 4.0" and persona["license_url"] == attribution.CC_BY_URL
    assert persona["source_revision"] == REV and persona["modified"] is True and persona["changes"]
    notice = block["notice"]
    for needle in ("Nemotron-Personas-Korea", "CC BY 4.0", "revision ada0f5b", "가공", "2025 가계금융복지조사",
                   "출처 표기", "공공누리 제1유형", "실제 여론이 아닙니다", attribution.SOURCES_URL):
        assert needle in notice, needle


def test_revision_is_recorded_verified_or_unknown_never_guessed():
    assert attribution.revision({"source_revision": REV, "revision_status": "user_supplied"}) == (REV, "user_supplied")
    with_addons = "4b5aa1c42bfd+addons-digital-0123abcd"
    assert attribution.revision({"panel_version": with_addons}) == (REV, "verified_saved_panel")
    assert attribution.revision({"panel_version": "ffffffffffff"}) == (None, "unknown")
    assert attribution.revision(None) == (None, "unknown")
    user = attribution.build({"source_revision": REV, "revision_status": "user_supplied"})
    assert "검증 안 됨" in user["notice"]
    verified = attribution.build({"panel_version": "4b5aa1c42bfd"})["sources"][0]
    assert verified["revision_evidence"] == attribution.PROVENANCE_URL
    assert "기록 없음" in attribution.build({})["notice"]


def test_recorded_reads_the_sidecar_without_hashing(tmp_path):
    data = tmp_path / "panel.jsonl.gz"
    assert attribution.recorded(data) == {}
    (tmp_path / "panel.jsonl.gz.meta.json").write_text(json.dumps(
        {"source_repo": attribution.NEMOTRON_REPO, "source_revision": REV, "revision_status": "resolved", "seed": 1}))
    assert attribution.recorded(data) == {"source_repo": attribution.NEMOTRON_REPO, "source_revision": REV,
                                          "revision_status": "resolved"}


def test_addon_statistics_and_short_credit():
    stats = attribution.addon_statistics(["finance", "digital", "finance"])
    assert stats[0] == "2025 가계금융복지조사" and stats.count("2025 가계금융복지조사") == 1
    assert "2025 디지털정보격차 실태조사" in stats
    line = attribution.short(attribution.build({"source_revision": REV}))
    assert "CC BY 4.0, revision ada0f5b" in line and "가공" in line


def test_validate_flags_a_block_that_lost_its_credit():
    assert attribution.validate(None) == ["attribution missing"]
    block = attribution.build({})
    block["sources"] = [s for s in block["sources"] if s["role"] != "synthetic_personas"]
    assert any("synthetic persona" in e for e in attribution.validate(block))
    stats = attribution.build({}, stats=["x"])
    stats["sources"][1]["items"] = []
    assert any("public statistics" in e for e in attribution.validate(stats))


def test_export_panel_full_writes_a_credited_sidecar(persona_db, tmp_path, monkeypatch):
    import gzip

    spec = importlib.util.spec_from_file_location("export_panel_full", ENGINE / "scripts" / "export_panel_full.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    panel_path, out = tmp_path / "panel-20k.jsonl.gz", tmp_path / "panel-20k-full.jsonl.xz"
    panel_path.write_bytes(gzip.compress(b"".join(json.dumps({"uuid": f"u{i:05d}"}).encode() + b"\n" for i in (1, 2))))
    monkeypatch.setattr(script, "PANEL", panel_path)
    monkeypatch.setattr(script, "OUT", out)
    (tmp_path / "persona.db.meta.json").write_text(json.dumps({"source_revision": REV, "revision_status": "resolved"}))
    assert script.main() == 0
    meta = json.loads((tmp_path / "panel-20k-full.jsonl.xz.meta.json").read_text(encoding="utf-8"))
    assert meta["source_revision"] == REV and attribution.validate(meta["attribution"]) == []
    assert "행 번호(id)만 빼고" in " ".join(meta["attribution"]["sources"][0]["changes"])


# --- group names, digital proxy and income bands -------------------------------------------------------------------

def _people(n: int, household: str, every: int) -> list[dict]:
    """Synthetic panel members; every `every`-th one has `household`, the rest live with a spouse."""
    people = []
    for i in range(n):
        family = household if i % every == 0 else "배우자와 거주"
        profile = (f"이름: (이름 없음)\n성별·나이: 여자, 45세\n사는 곳: 서울-중구 (서울)\n직업: 사무 보조원\n"
                   f"학력: 고등학교 / 혼인: 배우자있음\n가구: {family} / 주거: 연립주택\n\n평범하게 지냅니다.")
        people.append({"uuid": f"p{i:04d}", "age_band": "40대", "sex": "여자" if i % 2 else "남자", "capital": True,
                       "province": "서울", "profile": profile})
    return people


def _answers(people, minority):
    main = {p["uuid"]: ([0.2, 0.7, 0.1] if minority(p) else [0.6, 0.3, 0.1]) for p in people}
    return {"main": main, "placebo": dict(main), "reversed": dict(main)}


def test_household_card_names_composition_not_eligibility():
    people = _people(600, "자녀와 거주 (한부모)", 3)
    answers = _answers(people, lambda p: "(한부모)" in p["profile"])
    v = visit.view(SPEC, people, answers, OPTIONS, "4b5aa1c42bfd", everyone=people, context={}, roster={})
    card = next(c for c in v["cards"] if c["attribute"] == "가구")
    assert card["group"] == visit.CHILDREN_NO_SPOUSE and "한부모" not in card["group"]
    assert "한부모가족 지원기관" not in card["venues"] and card["caution"] == config.FAMILY_NOTE
    assert "주의: " + config.FAMILY_NOTE in v["copy_text"] and "Nemotron-Personas-Korea(CC BY 4.0" in v["copy_text"]
    assert attribution.validate(v["attribution"]) == []
    assert v["attribution"]["sources"][0]["source_revision"] == REV


def test_roster_lookup_reads_the_label_saved_before_the_rename():
    roster = {"n": 1000, "districts": {"서울 중구": 600, "부산 중구": 400},
              "groups": {"한부모 가구": {"서울 중구": 40, "부산 중구": 10}}}
    got = visit.where_roster(visit.CHILDREN_NO_SPOUSE, roster)
    assert got and got["people"] == 50 and got["source"] == "1m"


def test_digital_card_is_an_information_finding_proxy():
    people = _people(600, "배우자와 거주", 1)
    poor = {p["uuid"] for i, p in enumerate(people) if i % 3 == 0}
    context = {p["uuid"]: {"digital": "poor" if p["uuid"] in poor else "good"} for p in people}
    answers = _answers(people, lambda p: p["uuid"] in poor)
    v = visit.view(SPEC, people, answers, OPTIONS, "4b5aa1c42bfd+addons-digital-0123abcd", everyone=people,
                   context=context, roster={})
    card = next(c for c in v["cards"] if c["attribute"] == "digital")
    assert card["group"] == "인터넷·스마트폰으로 정보 찾기를 어려워하는 사람"
    assert card["caution"] == aggregate.DIGITAL_LIMIT and "앱 신청" in card["caution"]
    assert "공공 통계로 배정한 생활 여건" in " ".join(v["attribution"]["sources"][0]["changes"])
    assert "2025 디지털정보격차 실태조사" in v["attribution"]["sources"][1]["items"]


def test_result_attaches_attribution_and_money_and_digital_limits():
    people = _people(300, "배우자와 거주", 1)
    answers = _answers(people, lambda p: False)
    res = aggregate.summarize({"options": OPTIONS}, people, answers, [],
                              panel_version="4b5aa1c42bfd+addons-finance.digital-0123abcd")
    cautions = " ".join(res["cautions"])
    assert aggregate.MONEY_LIMIT in cautions and aggregate.DIGITAL_LIMIT in cautions
    assert attribution.validate(res["attribution"]) == []
    assert "2025 가계금융복지조사" in res["attribution"]["sources"][1]["items"]
    plain = aggregate.summarize({"options": OPTIONS}, people, answers, [], panel_version="ffffffffffff")
    assert [s["role"] for s in plain["attribution"]["sources"]] == ["synthetic_personas", "generated"]
    assert plain["attribution"]["sources"][0]["source_revision"] is None  # an unverified panel: not guessed
    assert aggregate.MONEY_LIMIT not in " ".join(plain["cautions"])
    # The verified 20k panel also matches the stored 2024 social survey diagnosis, which then is credited too.
    checked = aggregate.summarize({"options": OPTIONS}, people, answers, [], panel_version="4b5aa1c42bfd")
    assert checked["accuracy"]["payload"]["historical_baseline"]["panel_version"] == "4b5aa1c42bfd"
    assert "2024 사회조사" in checked["attribution"]["sources"][1]["items"][0]


@pytest.mark.parametrize("question, code", [
    ("이 지원금을 매달 얼마나 받으실 것 같습니까?", "amount_calc"),
    ("본인이 기초연금 수급 자격이 있으십니까?", "amount_calc"),
    ("이 사업의 지원 대상에 해당하십니까?", "amount_calc"),
    ("대출금을 제때 갚을 수 있으십니까?", "amount_calc"),
    ("정부24 앱으로 직접 신청하실 수 있습니까?", "procedure_ability"),
    ("필요한 서류를 직접 제출하실 수 있습니까?", "procedure_ability"),
])
def test_lint_warns_on_questions_the_panel_cannot_answer(question, code):
    found = [f for f in lint.check("", question, OPTIONS) if f["code"] == code]
    assert found and found[0]["level"] == "warn"


@pytest.mark.parametrize("question", [
    "만 70세 이상을 지원 대상에 포함하는 것에 찬성하십니까?",
    "온라인으로 신청할 수 있게 하는 것에 찬성하십니까?",
    "이 정책이 생활에 얼마나 도움이 된다고 보십니까?",
    "신청 자격을 완화하는 데 찬성하십니까?",
    "이 변화를 얼마나 받아들일 수 있습니까?",
])
def test_lint_leaves_opinion_questions_alone(question):
    codes = {f["code"] for f in lint.check("", question, OPTIONS)}
    assert not codes & {"amount_calc", "procedure_ability"}


def test_rule_view_never_judges_income_from_a_drawn_band():
    rule = {key: None for key in lh.RULE_KEYS} | {"income_max_manwon": 3000}
    assert lh.eligible(rule, {"income": "lt10", "age": 40, "working": True}) is None
    assert lh.eligible(rule, {"income_amt": 2500, "age": 40, "working": True}) is True


def test_income_band_reaches_the_model_as_a_range_not_a_midpoint():
    text = life_context.block({"income": "10_30", "debt": False, "skipped": []}, "finance")
    assert life_context.INCOME_KO["10_30"] in text and "2000" not in text and "2,000" not in text


def test_band_midpoints_stay_inside_calibration_code():
    allowed = {"pp/life_context.py", "pp/survey_match.py", "scripts/build_life_context.py"}
    users = set()
    for path in ENGINE.rglob("*.py"):
        rel = path.relative_to(ENGINE).as_posix()
        if rel.startswith("tests/") or "/." in rel:
            continue
        if re.search(r"\bINCOME_MIDPOINT\b|\b_income_point\b", path.read_text(encoding="utf-8")):
            users.add(rel)
    assert users <= allowed, users - allowed
