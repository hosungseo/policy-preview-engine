"""Tests for field verification log (현장 확인 회수 기록) schema, PII guard, reconciliation, and CLI."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pp import field_log

VISIT_PREDICTIONS = {
    "policy_title": "시내버스 요금 지원 안내문",
    "run_id": "u_demo1234",
    "cards": [
        {"group": "70세 이상", "say": "찬성 80%", "venues": ["경로당·노인복지관"]},
        {"group": "19–29세", "say": "잘 모르겠다 40%", "venues": ["대학·청년센터"]},
    ],
    "missing": [
        {"who": "농어민", "route": "농·수협, 이장단 회의", "party": True},
        {"who": "만 19세 미만", "route": "학교", "party": False},
    ],
}

PLAN_PREDICTIONS = {
    "overview": {"title": "무임승차 연령 조정"},
    "issues": [
        {"id": "i1", "title": "교통비 부담 증가", "summary": "통근·통원 비용 우려"},
        {"id": "i2", "title": "기초연금 예외 확인 절차", "summary": "증빙 서류 부담"},
    ],
    "outreach": [
        {"group": "70세 이상 · 비수도권", "channels": ["경로당"], "suggestion": {"why": "직접 영향"}},
    ],
}


def test_schema_file_exists_and_templates_are_valid():
    root = Path(__file__).resolve().parents[2]
    schema_path = root / "engine" / "schemas" / "field-verification-v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["properties"]["schema_version"]["const"] == field_log.SCHEMA_VERSION

    csv_tpl = root / "docs" / "templates" / "field-verification-template.csv"
    json_tpl = root / "docs" / "templates" / "field-verification-template.json"
    doc_csv = field_log.load_field_log(csv_tpl, policy_title="예시 정책 안내문")
    doc_json = field_log.load_field_log(json_tpl)
    assert len(doc_csv["entries"]) == 2 and len(doc_json["entries"]) == 2


def test_pii_is_blocked_in_field_logs(tmp_path):
    bad_json = tmp_path / "pii.json"
    bad_json.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "policy_title": "테스트",
                "entries": [
                    {
                        "entry_id": "fv-1",
                        "visit_date": "2026-11-27",
                        "group_label": "70세 이상",
                        "venue": "경로당",
                        "participant_count": 3,
                        "predicted_ref": "70세 이상",
                        "item_kind": "group",
                        "outcome": "hit",
                        "field_finding": "연락처 010-1234-5678로 문의하라고 안내됨",
                        "action_taken": "revised",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with pytest.raises(field_log.FieldLogError, match="휴대전화"):
        field_log.load_field_log(bad_json)

    bad_rrn = {
        "entry_id": "fv-2",
        "visit_date": "2026-11-27",
        "group_label": "70세 이상",
        "venue": "행정복지센터",
        "participant_count": 1,
        "predicted_ref": "70세 이상",
        "item_kind": "group",
        "outcome": "hit",
        "field_finding": "주민번호 900101-1234567 확인",
        "action_taken": "pending",
    }
    assert any("주민등록번호" in e for e in field_log.validate_entry(bad_rrn))


def test_reconcile_hits_false_positives_misses_and_unchecked():
    log_doc = {
        "schema_version": "1.0",
        "run_id": "u_demo1234",
        "policy_title": "시내버스 요금 지원 안내문",
        "entries": [
            {
                "entry_id": "fv-001",
                "visit_date": "2026-11-27",
                "group_label": "70세 이상",
                "venue": "경로당·노인복지관",
                "participant_count": 6,
                "predicted_ref": "card-1:70세 이상",
                "item_kind": "group",
                "outcome": "hit",
                "field_finding": "방문 신청 창구 위치가 안내문에 잘 보이지 않음",
                "action_taken": "revised",
                "review_minutes": 45,
            },
            {
                "entry_id": "fv-002",
                "visit_date": "2026-11-27",
                "group_label": "19–29세",
                "venue": "대학·청년센터",
                "participant_count": 4,
                "predicted_ref": "19–29세",
                "item_kind": "group",
                "outcome": "false_positive",
                "field_finding": "내용을 이미 잘 알고 있었고 별도 불만이 없었음",
                "action_taken": "no_change",
                "review_minutes": 30,
            },
            {
                "entry_id": "fv-003",
                "visit_date": "2026-11-27",
                "group_label": "대리 신청 가족",
                "venue": "행정복지센터",
                "participant_count": 2,
                "predicted_ref": None,
                "item_kind": "unpredicted",
                "outcome": "miss",
                "field_finding": "가족 대리 신청 시 위임장 서류 안내가 누락됨",
                "action_taken": "revised",
                "review_minutes": 25,
            },
        ],
    }
    report = field_log.reconcile(VISIT_PREDICTIONS, log_doc)
    s = report["summary"]
    assert s["predicted_total"] == 3  # 2 cards + 1 party missing
    assert s["hits"] == 1 and s["false_positives"] == 1 and s["misses"] == 1
    assert s["unchecked_predictions"] == 1  # 농어민 was not visited yet
    assert s["hit_rate_checked"] == 0.5
    assert s["revised_count"] == 2
    assert s["total_participants"] == 12
    assert s["total_review_minutes"] == 100

    md = field_log.render_reconciliation_markdown(report)
    assert "적중·오탐·놓침 요약" in md
    assert "합성이 놓친 현장 발견 목록" in md
    assert "대리 신청 가족" in md and "미방문(기록 없음)" in md


def test_extract_predictions_from_plan_and_cli_roundtrip(tmp_path):
    preds_path = tmp_path / "plan.json"
    preds_path.write_text(json.dumps(PLAN_PREDICTIONS, ensure_ascii=False), encoding="utf-8")
    csv_path = tmp_path / "field.csv"
    out_md = tmp_path / "reconcile.md"
    out_json = tmp_path / "reconcile.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_field_log.py"

    # 1) Generate CSV template pre-seeded from plan.json
    subprocess.run(
        [sys.executable, str(script), "--predictions", str(preds_path), "--init-csv", str(csv_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert csv_path.exists()
    content = csv_path.read_text(encoding="utf-8-sig")
    assert "교통비 부담 증가" in content and "기초연금 예외 확인 절차" in content

    # 2) Validate and reconcile the generated CSV against plan.json
    subprocess.run(
        [
            sys.executable,
            str(script),
            "--predictions",
            str(preds_path),
            "--field-log",
            str(csv_path),
            "--out-md",
            str(out_md),
            "--out-json",
            str(out_json),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    rec = json.loads(out_json.read_text(encoding="utf-8"))
    assert rec["summary"]["predicted_total"] == 3  # 2 issues + 1 outreach group
    assert rec["summary"]["misses"] == 1
    assert "현장 확인 회수 대조표" in out_md.read_text(encoding="utf-8")
