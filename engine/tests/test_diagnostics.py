"""Tests for automated diagnostics (dispersion compression, edu/income inflation, question reliability, metrics)."""
from __future__ import annotations

from pp import diagnostics, plan_doc
from ppservice.survey import aggregate, lint, visit


def _make_people(n: int = 80) -> list[dict]:
    bands = ["19–29세", "30대", "40대", "50대", "60대", "70세 이상"]
    edus = ["중학교", "고등학교", "4년제 대학교", "대학원"]
    incomes = ["lt10", "mid", "ge100"]
    out = []
    for i in range(n):
        band = bands[i % len(bands)]
        age = {"19–29세": 25, "30대": 35, "40대": 45, "50대": 55, "60대": 65, "70세 이상": 74}[band]
        sex = "여자" if i % 2 else "남자"
        prov = "서울" if i % 2 == 0 else "부산"
        edu = edus[i % len(edus)]
        inc = incomes[i % len(incomes)]
        out.append(
            {
                "uuid": f"p{i:04d}",
                "sex": sex,
                "age": age,
                "age_band": band,
                "province": prov,
                "capital": prov == "서울",
                "education_level": edu,
                "income": inc,
                "profile": f"성별·나이: {sex}, {age}세 / 사는 곳: {prov}-중구 / 학력: {edu}\n\n설명입니다.",
            }
        )
    return out


def test_question_reliability_pre_run_alerts_and_lint_integration():
    # Standard 3-option policy question triggers no reliability alerts
    plain = lint.check("시내버스 요금을 지원합니다.", "만 70세 이상 시내버스 요금 전액 지원에 찬성하십니까?", ["찬성", "반대", "잘 모르겠다"])
    assert not any(f["code"].startswith("reliability_") for f in plain)

    # 4~5 options triggers reliability_many_options (info, not block)
    many = lint.check(
        "시내버스 요금을 지원합니다.",
        "만 70세 이상 시내버스 요금 지원에 찬성하십니까?",
        ["매우 찬성", "대체로 찬성", "보통", "대체로 반대", "매우 반대"],
    )
    assert any(f["code"] == "reliability_many_options" and f["level"] == "info" for f in many)
    assert not lint.blocked(many)

    # Subjective feeling wording triggers reliability_subjective_topic (info)
    subj = lint.check(
        "근로환경 안내문입니다.",
        "평소 직장 생활에서 스트레스를 얼마나 느끼십니까?",
        ["많이 느낀다", "보통이다", "거의 느끼지 않는다"],
    )
    assert any(f["code"] == "reliability_subjective_topic" and f["level"] == "info" for f in subj)
    assert not lint.blocked(subj)


def test_dispersion_compression_warning():
    people = _make_people(60)
    spec = {"question": "지원에 찬성하십니까?", "options": ["찬성", "반대", "잘 모르겠다"]}
    # Everyone gives nearly the exact same probabilities -> dispersion compression
    answers = {p["uuid"]: [0.60, 0.25, 0.15] for p in people}
    diag = diagnostics.diagnose_survey(spec, people, answers)
    codes = {w["code"] for w in diag["warnings"]}
    assert "dispersion_compression" in codes
    assert diag["metrics"]["between_person_sd"] == 0.0
    assert diag["metrics"]["majority_clustering_share"] == 1.0


def test_edu_income_overestimation_warning():
    people = _make_people(120)
    spec = {"question": "지원에 찬성하십니까?", "options": ["찬성", "반대", "잘 모르겠다"]}
    # Responses driven almost purely by education and income -> triggers edu_income_overestimation
    answers = {}
    for p in people:
        if p["education_level"] in ("4년제 대학교", "대학원") and p["income"] == "ge100":
            answers[p["uuid"]] = [0.90, 0.05, 0.05]
        elif p["education_level"] == "중학교" or p["income"] == "lt10":
            answers[p["uuid"]] = [0.15, 0.70, 0.15]
        else:
            answers[p["uuid"]] = [0.55, 0.30, 0.15]
    diag = diagnostics.diagnose_survey(spec, people, answers)
    codes = {w["code"] for w in diag["warnings"]}
    assert "edu_income_overestimation" in codes
    assert diag["metrics"]["edu_income_share_of_explained"] >= diagnostics.EDU_INCOME_SHARE_WARN


def test_high_answer_variability_warning():
    people = _make_people(60)
    spec = {"question": "지원에 찬성하십니까?", "options": ["찬성", "반대", "잘 모르겠다"]}
    # Spread individuals so dispersion isn't compressed, while aggregate mean is nearly uniform (1/3, 1/3, 1/3)
    answers = {}
    for i, p in enumerate(people):
        mod = i % 3
        answers[p["uuid"]] = [0.8, 0.1, 0.1] if mod == 0 else ([0.1, 0.8, 0.1] if mod == 1 else [0.1, 0.1, 0.8])
    diag = diagnostics.diagnose_survey(spec, people, answers)
    codes = {w["code"] for w in diag["warnings"]}
    assert "high_answer_variability" in codes
    assert "dispersion_compression" not in codes
    assert diag["metrics"]["answer_variability"] >= 0.99


def test_multidimensional_accuracy_metrics():
    # Identical distributions
    assert diagnostics.jsd([0.5, 0.3, 0.2], [0.5, 0.3, 0.2]) == 0.0
    assert diagnostics.nmd_soft_similarity([0.5, 0.3, 0.2], [0.5, 0.3, 0.2]) == 1.0
    # Extreme shift on 3-point ordinal scale
    assert diagnostics.nmd_soft_similarity([1.0, 0.0, 0.0], [0.0, 0.0, 1.0]) == 0.0
    # Adjacent shift scores higher than far shift
    near = diagnostics.nmd_soft_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0])
    far = diagnostics.nmd_soft_similarity([1.0, 0.0, 0.0], [0.0, 0.0, 1.0])
    assert near > far and diagnostics.jsd([1.0, 0.0, 0.0], [0.0, 0.0, 1.0]) == 1.0

    # Majority-only predictor gets Informedness J == 0 even if accuracy is high
    y_true = [1, 1, 1, 1, 1, 1, 1, 1, 0, 0]
    y_maj = [1] * 10
    assert diagnostics.informedness_j(y_true, y_maj) == 0.0
    assert diagnostics.informedness_j(y_true, y_true) == 1.0

    # Equity DPI
    dpi = diagnostics.equity_dpi({"청년": 0.04, "고령층": 0.19, "중년": 0.08})
    assert dpi["worst_group"] == "고령층" and dpi["best_group"] == "청년" and abs(dpi["dpi"] - 0.15) < 1e-6


def test_aggregate_visit_and_plan_doc_surface_diagnostic_warnings():
    people = _make_people(400)
    spec = {
        "title": "체감 정책(테스트)",
        "policy_text": "체감 만족도를 높이는 정책입니다.",
        "question": "이 정책에 대해 전반적으로 만족하십니까?",
        "options": ["매우 만족", "만족", "반대", "매우 반대"],
    }
    main = {}
    for p in people:
        # Strong education split to produce an education card in visit.view() and trigger warning
        if p["education_level"] in ("4년제 대학교", "대학원"):
            main[p["uuid"]] = [0.75, 0.15, 0.05, 0.05]
        else:
            main[p["uuid"]] = [0.10, 0.10, 0.65, 0.15]
    answers = {"main": main, "placebo": dict(main), "reversed": dict(main), "no_persona": {"np": [0.42, 0.13, 0.35, 0.10]}}

    # aggregate.summarize with include_diagnostics=True attaches diagnostics, persona_net_effect, and cautions
    res = aggregate.summarize(spec, people, answers, [], include_diagnostics=True)
    assert "diagnostics" in res and "persona_net_effect" in res
    assert any("학력·소득" in c for c in res["cautions"])
    assert any("선택지가 4개" in c for c in res["cautions"])

    # visit.view attaches education/income caution tag on matching cards and diagnostics summary
    v = visit.view(spec, people, answers, spec["options"], None, everyone=people, context={}, roster={})
    assert "diagnostics" in v and v["warnings"]
    edu_cards = [c for c in v["cards"] if c["attribute"] == "학력"]
    assert edu_cards and all("학력·소득" in c.get("caution", "") for c in edu_cards)

    # plan_doc.build_plan carries warnings and diagnostics when passed
    analysis = {"overall": {"n": 40}, "overall_aff": {"n": 10}, "issues": [], "outreach": [], "suggestions": []}
    plan = plan_doc.build_plan(
        {"title": spec["title"], "kind": "가상 정책안"},
        analysis,
        [],
        [],
        {"created_at": "2026-11-27T01:00:00+00:00"},
        diagnostics=res["diagnostics"],
    )
    assert "diagnostics" in plan and len(plan["warnings"]) >= 2


def test_diagnose_jev_rows_adapter():
    people = {p["uuid"]: p for p in _make_people(40)}
    rows = [{"uuid": u, "stance_probs": [0.05, 0.10, 0.70, 0.10, 0.05]} for u in people]
    diag = diagnostics.diagnose_jev_rows(rows, people)
    assert diag["n"] == 40
    assert any(w["code"] == "dispersion_compression" for w in diag["warnings"])
