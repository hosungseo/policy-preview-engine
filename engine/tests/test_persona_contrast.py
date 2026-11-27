"""Tests for 3-arm persona net-effect comparison (mock-only, zero paid calls)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pp import persona_contrast

SPEC = {
    "title": "대중교통 요금 지원(모의 시험)",
    "policy_text": "만 70세 이상 시민에게 시내버스 요금을 월 5만 원 한도로 지원합니다.",
    "question": "만 70세 이상 시내버스 요금 지원에 찬성하십니까?",
    "options": ["찬성", "반대", "잘 모르겠다"],
}


def _fake_model_eval(state: dict, questions: dict, **kwargs):
    """Deterministic fake non-mock model: no_persona leans neutral, manual leans mixed, synthetic shifts strongly."""
    person = state.get("person")
    if person is None:
        probs = {"o1": 0.40, "o2": 0.30, "o3": 0.30}
    elif "생활 여건:" in person:  # manual condition
        probs = {"o1": 0.50, "o2": 0.30, "o3": 0.20}
    else:  # synthetic persona: vary cleanly by age across bands (not edu/income)
        if "74세" in person or "65세" in person:
            p1 = 0.88
        elif "55세" in person or "45세" in person:
            p1 = 0.68
        else:
            p1 = 0.52
        probs = {"o1": p1, "o2": round((1 - p1) * 0.6, 4), "o3": round((1 - p1) * 0.4, 4)}
    return {"model": "fake-eval-v1", "usage": {"input_tokens": 500}, "answers": {"q": {"type": "choice", "probabilities": probs}}}


def _flat_eval(state: dict, questions: dict, **kwargs):
    """Persona has zero effect (identical probabilities regardless of person)."""
    return {
        "model": "fake-eval-v1",
        "usage": {"input_tokens": 400},
        "answers": {"q": {"type": "choice", "probabilities": {"o1": 0.50, "o2": 0.30, "o3": 0.20}}},
    }


def test_mock_contrast_always_holds_expansion_decision(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    people = persona_contrast.make_demo_synthetic_people(24)
    report = persona_contrast.run_contrast(
        SPEC,
        people,
        manual_issues=[{"id": "i1", "title": "신청 창구 안내 부족"}],
        synthetic_issues=[
            {"id": "i1", "title": "신청 창구 안내 부족"},
            {"id": "i2", "title": "농어촌 버스 노선 예외 미기재", "actionable": True, "verified_against_text": True},
        ],
    )
    assert report["mode"] == "mock"
    assert set(report["arms"]) == {"no_persona", "manual", "synthetic"}
    assert report["arms"]["no_persona"]["calls"] == 2
    assert report["arms"]["manual"]["calls"] == 2 * len(persona_contrast.DEFAULT_MANUAL_CONDITIONS)
    assert report["arms"]["synthetic"]["calls"] == 2 * 24
    # Mock output must NEVER recommend expanding
    assert report["expansion_decision"]["status"] == "pending_human_review"
    assert report["issue_comparison"]["new_actionable_count"] == 1
    md = persona_contrast.render_markdown_report(report)
    assert "(a) 인물 없음" in md and "(b) 수작업 소수 조건" in md and "(c) 합성 인물" in md
    assert "새로 고칠 문제가 늘었을 때만 확대" in md
    assert "자동 진단 경고" in md


def test_expansion_decision_expand_vs_do_not_expand():
    people = persona_contrast.make_demo_synthetic_people(60)

    # Case 1: real-like lift > noise AND new verified actionable issue AND no diagnostic warnings -> expand
    rep_expand = persona_contrast.run_contrast(
        SPEC,
        people,
        evaluate=_fake_model_eval,
        manual_issues=[{"id": "m1", "title": "창구 안내 부족"}],
        synthetic_issues=[
            {"id": "m1", "title": "창구 안내 부족"},
            {"id": "s1", "title": "환승 할인 중복 기준 불명확", "actionable": True, "verified_against_text": True},
        ],
    )
    assert rep_expand["mode"] == "model"
    assert rep_expand["net_effect"]["clears_noise"] is True
    assert rep_expand["expansion_decision"]["status"] == "expand"

    # Case 2: lift > noise, but synthetic found NO new actionable issues over manual -> do_not_expand
    rep_dup = persona_contrast.run_contrast(
        SPEC,
        people,
        evaluate=_fake_model_eval,
        manual_issues=[{"id": "m1", "title": "창구 안내 부족"}],
        synthetic_issues=[
            {"id": "m1", "title": "창구 안내 부족"},
            {"id": "s2", "title": "문안 미확인 추정", "actionable": True, "verified_against_text": False},
        ],
    )
    assert rep_dup["issue_comparison"]["new_actionable_count"] == 0
    assert rep_dup["expansion_decision"]["status"] == "do_not_expand"

    # Case 3: persona adds zero lift over no-persona baseline -> do_not_expand + low_persona_net_effect warning
    rep_flat = persona_contrast.run_contrast(SPEC, people, evaluate=_flat_eval)
    assert rep_flat["net_effect"]["persona_lift_vs_no_persona_pp"] == 0.0
    assert rep_flat["expansion_decision"]["status"] == "do_not_expand"
    assert any(w["code"] == "low_persona_net_effect" for w in rep_flat["diagnostics"]["warnings"])


def test_compare_persona_baseline_cli_mock_and_custom_manual(tmp_path):
    manual_file = tmp_path / "manual.json"
    manual_file.write_text(
        json.dumps(
            [
                {"id": "c1", "label": "고령층", "profile": "75세 혼자 사는 어르신"},
                {"id": "c2", "label": "직장인", "profile": "35세 맞벌이 직장인"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"
    script = Path(__file__).resolve().parents[1] / "scripts" / "compare_persona_baseline.py"
    policy = Path(__file__).resolve().parents[1] / "policies" / "subway-free-ride.json"

    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--policy",
            str(policy),
            "--question",
            SPEC["question"],
            "--options",
            *SPEC["options"],
            "--manual",
            str(manual_file),
            "--n",
            "20",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.returncode == 0
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved["mode"] == "mock" and saved["arms"]["manual"]["n"] == 2 and saved["arms"]["synthetic"]["n"] == 20
    md = out_md.read_text(encoding="utf-8")
    assert "세 조건 대조 표" in md and "담당자 최종 판단 칸" in md
