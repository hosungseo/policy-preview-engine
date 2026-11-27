"""CLI script for field verification logs (현장 확인 회수 기록): template generation, validation, and reconciliation.

Examples:
  # 1) Create a blank or prediction-seeded CSV/JSON template
  python engine/scripts/reconcile_field_log.py --init-csv /tmp/field.csv [--predictions plan.json]
  python engine/scripts/reconcile_field_log.py --init-json /tmp/field.json [--predictions visit.json]

  # 2) Reconcile field results against predicted blockers/groups and emit a hit/miss table
  python engine/scripts/reconcile_field_log.py \\
    --predictions /tmp/visit.json \\
    --field-log /tmp/field.csv \\
    --out-md /tmp/reconciliation.md --out-json /tmp/reconciliation.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import field_log  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="현장 확인 회수 기록 템플릿 생성, 형식·개인정보 검사 및 예측-현장 적중·놓침 대조표 생성"
    )
    ap.add_argument("--predictions", type=Path, default=None, help="미리보기 예측 JSON (visit / plan / bundle / 일반 형식)")
    ap.add_argument("--field-log", type=Path, default=None, help="현장 확인 회수 기록 파일(.csv 또는 .json)")
    ap.add_argument("--policy-title", default="", help="CSV 사용 시 정책 제목(생략 시 예측 파일 또는 파일명)")
    ap.add_argument("--run-id", default="", help="CSV 사용 시 실행 ID(생략 시 예측 파일 또는 파일명)")
    ap.add_argument("--init-csv", type=Path, default=None, help="현장 기록용 CSV 템플릿 생성 경로")
    ap.add_argument("--init-json", type=Path, default=None, help="현장 기록용 JSON 템플릿 생성 경로")
    ap.add_argument("--validate-only", action="store_true", help="형식·개인정보 검사만 수행")
    ap.add_argument("--out-md", type=Path, default=None, help="적중·놓침 대조표 마크다운 저장 경로")
    ap.add_argument("--out-json", type=Path, default=None, help="적중·놓침 대조 결과 JSON 저장 경로")
    args = ap.parse_args(argv)

    predictions_raw = json.loads(args.predictions.read_text(encoding="utf-8")) if args.predictions else None

    if args.init_csv or args.init_json:
        if args.init_csv:
            dest = field_log.write_template_csv(args.init_csv, predictions_raw)
            print(f"CSV 템플릿을 만들었습니다: {dest}")
        if args.init_json:
            dest = field_log.write_template_json(
                args.init_json,
                predictions_raw,
                run_id=args.run_id or "example-run",
                policy_title=args.policy_title or "예시 정책 안내문",
            )
            print(f"JSON 템플릿을 만들었습니다: {dest}")
        return 0

    if not args.field_log:
        raise SystemExit("--field-log 파일 또는 --init-csv / --init-json 중 하나를 지정해 주세요.")

    try:
        log_doc = field_log.load_field_log(args.field_log, policy_title=args.policy_title, run_id=args.run_id)
    except field_log.FieldLogError as e:
        print(f"[오류] 현장 확인 기록 검증 실패: {e}", file=sys.stderr)
        return 2

    if args.validate_only:
        print(f"검증 통과: {args.field_log} (기록 {len(log_doc['entries'])}건)")
        return 0

    report = field_log.reconcile(predictions_raw or {}, log_doc)
    md = field_log.render_reconciliation_markdown(report)

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
    if not args.out_md:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
