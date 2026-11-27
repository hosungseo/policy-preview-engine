"""Operator commands.

  python -m ppservice serve [--host 127.0.0.1] [--port 8800]
  python -m ppservice user add EMAIL          prints a new access code once
  python -m ppservice user reset-code EMAIL   prints a new code, ends that user's sessions
  python -m ppservice user list
  python -m ppservice user delete EMAIL       deletes the user and all their previews
  python -m ppservice cleanup                 deletes previews past PP_RETENTION_DAYS
  python -m ppservice reaggregate             recomputes every finished result from stored answers (no model calls)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import auth, jobs
from .db import Database
from .settings import load


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ppservice")
    sub = ap.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8800)
    user = sub.add_parser("user")
    user.add_argument("action", choices=["add", "reset-code", "list", "delete"])
    user.add_argument("email", nargs="?")
    sub.add_parser("cleanup")
    sub.add_parser("reaggregate")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = load()
    if args.cmd == "serve":
        if (os.environ.get("PP_LLM_PROVIDER") or "").strip().lower() == "exaone":
            if args.host not in ("127.0.0.1", "::1", "localhost"):
                ap.error("EXAONE 연결은 로컬 비상업 검증 전용입니다. 외부 주소에 서버를 열 수 없습니다.")
            if (os.environ.get("PP_EXAONE_LOCAL_ONLY") or "").strip() != "1":
                ap.error("EXAONE 로컬 검증 설정(PP_EXAONE_LOCAL_ONLY=1)이 필요합니다.")
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port, workers=1, proxy_headers=False)
        return 0
    db = Database(settings.db_path)
    if args.cmd == "cleanup":
        print(jobs.cleanup(db, settings))
        return 0
    if args.cmd == "reaggregate":
        print(f"{jobs.reaggregate(db)}개 결과를 다시 계산했습니다.")
        return 0
    if args.action == "list":
        for row in db.all("SELECT email, created_at, disabled FROM users ORDER BY id"):
            print(f"{row['email']}\t{row['created_at']}\t{'disabled' if row['disabled'] else 'active'}")
        return 0
    if not args.email:
        ap.error("EMAIL이 필요합니다")
    if args.action == "add":
        print(f"{auth.normalize_email(args.email)} 접속 코드: {auth.add_user(db, args.email)}  (다시 표시되지 않습니다)")
    elif args.action == "reset-code":
        print(f"새 접속 코드: {auth.reset_code(db, args.email)}  (다시 표시되지 않습니다)")
    elif args.action == "delete":
        with db.tx() as con:
            con.execute("DELETE FROM users WHERE email=?", (auth.normalize_email(args.email),))
        db.checkpoint()
        print("삭제했습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
