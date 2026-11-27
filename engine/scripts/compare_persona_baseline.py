"""CLI script for optional 3-arm persona net-effect comparison (mock-safe by default).

Examples (0 won, mock mode):
  python engine/scripts/compare_persona_baseline.py \\
    --policy engine/policies/subway-free-ride.json \\
    --question "지하철 무임승차 기준 연령을 70세로 단계 상향하는 데 찬성하십니까?" \\
    --options "찬성" "반대" "잘 모르겠다" \\
    --out-md /tmp/contrast.md --out-json /tmp/contrast.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pp import budget, jev, persona_contrast  # noqa: E402
from ppservice.survey import panel  # noqa: E402


def _load_policy(args) -> dict:
    if args.policy:
        data = json.loads(args.policy.read_text(encoding="utf-8"))
        return {
            "title": data.get("title") or args.title or args.policy.stem,
            "policy_text": data.get("text") or data.get("policy_text") or "",
            "question": args.question or data.get("question") or f"‘{data.get('title', '이 정책')}’에 찬성하십니까?",
            "options": args.options or data.get("options") or ["찬성", "반대", "잘 모르겠다"],
        }
    if not args.title or not args.policy_text or not args.question:
        raise SystemExit("--policy 파일 또는 --title, --policy-text, --question을 모두 지정해 주세요.")
    return {
        "title": args.title,
        "policy_text": args.policy_text,
        "question": args.question,
        "options": args.options or ["찬성", "반대", "잘 모르겠다"],
    }


def _load_synthetic(n: int, seed: int, personas_path: Path | None) -> list[dict]:
    if personas_path:
        raw = json.loads(personas_path.read_text(encoding="utf-8"))
        people = raw.get("personas") if isinstance(raw, dict) else raw
        return list(people)[:n]
    if panel.BUNDLE.exists():
        all_people, _ = panel.load(addons="off")
        return panel.sample(all_people, n, seed)
    return persona_contrast.make_demo_synthetic_people(n)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="인물 순효과 대조: (a) 인물 없음 vs (b) 수작업 소수 조건 vs (c) 합성 인물 비교(기본 mock 0원)"
    )
    ap.add_argument("--policy", type=Path, help="정책 JSON 파일 경로 (예: engine/policies/subway-free-ride.json)")
    ap.add_argument("--title", default="", help="정책 제목(--policy 미사용 시)")
    ap.add_argument("--policy-text", default="", help="정책 본문(--policy 미사용 시)")
    ap.add_argument("--question", default="", help="설문 문항")
    ap.add_argument("--options", nargs="+", default=None, help="선택지 목록(2~5개)")
    ap.add_argument("--manual", type=Path, default=None, help="수작업 소수 조건 JSON 파일(생략 시 기본 5개 예시)")
    ap.add_argument("--personas", type=Path, default=None, help="합성 인물 JSON 파일(생략 시 패널 묶음 또는 모의 예시)")
    ap.add_argument("--issues", type=Path, default=None, help="세 조건별 발견 문제 JSON 파일(선택)")
    ap.add_argument("--n", type=int, default=40, help="합성 인물 표본 수(기본 40)")
    ap.add_argument("--seed", type=int, default=42, help="표본 추출 시드(기본 42)")
    ap.add_argument("--no-reversed", action="store_true", help="선택지 순서 뒤집기 생략")
    ap.add_argument("--allow-paid", action="store_true", help="유료 판단 모델 호출 허용(미지정 시 mock만 허용)")
    ap.add_argument("--max-calls", type=int, default=100_000)
    ap.add_argument("--max-output-tokens", type=int, default=16_384)
    ap.add_argument("--max-cost-usd", type=float, default=10.0)
    ap.add_argument("--out-json", type=Path, default=None, help="결과 JSON 저장 경로")
    ap.add_argument("--out-md", type=Path, default=None, help="결과 마크다운 보고서 저장 경로")
    args = ap.parse_args(argv)

    if not args.allow_paid:
        os.environ["PP_JEV_PROVIDER"] = "mock"
    elif jev.provider() != "mock" and not jev.available():
        raise SystemExit("선택한 유료 판단 모델의 API 설정이 준비되지 않았습니다.")

    spec = _load_policy(args)
    manual = persona_contrast.load_manual_conditions(args.manual) if args.manual else None
    synthetic = _load_synthetic(args.n, args.seed, args.personas)

    issue_data = json.loads(args.issues.read_text(encoding="utf-8")) if args.issues else {}
    output_path = args.out_json or args.out_md
    ledger_path = output_path.with_suffix(output_path.suffix + ".budget.json") if output_path else None
    if ledger_path:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
    report = persona_contrast.run_contrast(
        spec,
        synthetic,
        manual_conditions=manual,
        no_persona_issues=issue_data.get("no_persona"),
        manual_issues=issue_data.get("manual"),
        synthetic_issues=issue_data.get("synthetic"),
        include_reversed=not args.no_reversed,
        review_minutes=issue_data.get("review_minutes"),
        limits=budget.Limits(max_calls=args.max_calls, max_output_tokens=args.max_output_tokens,
                             max_cost_usd=args.max_cost_usd),
        budget_path=ledger_path,
    )
    md = persona_contrast.render_markdown_report(report)

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
