"""Minimal public CLI; legacy research commands remain at python -m pp."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import budget, config, llm, public_rules, service


def main(argv: list[str] | None = None) -> int:
    class PublicParser(argparse.ArgumentParser):
        def _print_message(self, message, file=None):
            if message:
                super()._print_message(public_rules.NOTICE + "\n" + message, file)

    parser = PublicParser(prog="pp")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in ("run", "estimate"):
        p = sub.add_parser(command)
        p.add_argument("policy", type=Path, help="UTF-8 policy text (Markdown or plain text)")
        p.add_argument("--i-confirm-public", action="store_true", help="Confirm the text is already public despite draft markers")
        p.add_argument("--sample", type=int, default=service.DEFAULT_SAMPLE)
        p.add_argument("--max-calls", type=int, default=100000)
        p.add_argument("--max-output-tokens", type=int, default=16384)
        p.add_argument("--max-retries", type=int, default=2)
        p.add_argument("--max-concurrency", type=int, default=8)
        p.add_argument("--max-cost-usd", type=float, default=10.0)
        if command == "run":
            p.add_argument("--out", type=Path)
            p.add_argument("--seed", type=int, default=42)
    api = sub.add_parser("api")
    api.add_argument("--port", type=int, default=8765)
    sub.add_parser("mcp")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "api":
            import uvicorn
            from .api import create_app
            uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
            return 0
        if args.cmd == "mcp":
            from .mcp import main as mcp_main
            mcp_main()
            return 0
        limits = service.normalize_limits({k: getattr(args, k) for k in (
            "max_calls", "max_output_tokens", "max_retries", "max_concurrency", "max_cost_usd")})
        text = args.policy.read_text(encoding="utf-8")
        preview = service.estimate(text, args.sample, i_confirm_public=args.i_confirm_public, limits=limits)
        if args.cmd == "estimate":
            print(public_rules.dumps(preview))
            return 0
        print(public_rules.NOTICE + "\n실행 전 예상: " + public_rules.dumps(preview), file=sys.stderr, flush=True)
        result = service.run_policy(text, sample=args.sample, seed=args.seed, i_confirm_public=args.i_confirm_public, limits=limits)
        body = public_rules.dumps(result) + "\n"
        if args.out:
            args.out.write_text(body, encoding="utf-8")
        else:
            print(body, end="")
        return 0
    except (llm.LLMError, budget.BudgetExceeded):
        print(public_rules.NOTICE + "\nerror: 모델 응답 처리 실패. 키·잔액·연결과 문안을 확인하세요.", file=sys.stderr)
        return 2
    except service.RequestError as e:
        # Known local configuration errors contain no provider response or secret.
        print(f"{public_rules.NOTICE}\nerror: {e}", file=sys.stderr)
        return 2
    except (config.DataMissing, OSError, UnicodeDecodeError):
        print(public_rules.NOTICE + "\nerror: 파일·패널 자료 설정과 UTF-8 형식을 확인하세요.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
