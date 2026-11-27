"""Smoke: one real-Jev service run with "5년 뒤 보기" on a small panel, through the service's own job path, then
"대상 규칙으로 나눠 보기" on it.

  PP_JEV_PROVIDER=api PP_SURVEY_N=300 ../.venv/bin/python scripts/smoke_future.py

Costs about $0.10 at N=300 (five arms). Writes only into a fresh temp data folder, which is printed and left in place.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
tmp = tempfile.mkdtemp(prefix="pp-smoke-")
os.environ.setdefault("PP_SURVEY_N", "300")
os.environ.setdefault("PP_SURVEY_THREADS", "8")
os.environ.setdefault("PP_JEV_PROVIDER", "api")
os.environ.update({"PP_SERVICE_DATA": tmp, "PP_WEB_OUT": tmp + "/noweb"})

from ppservice import auth, jobs  # noqa: E402
from ppservice.db import Database, now  # noqa: E402
from ppservice.settings import load  # noqa: E402
from ppservice.survey import panel  # noqa: E402

POLICY = "개인 근로·사업소득이 하위 20%인 근로자에게 월 30만 원의 소득 보전금을 2027년부터 지급한다."
QUESTION = "이 소득 보전금 지급에 찬성하십니까?"
OPTIONS = ["찬성", "반대", "잘 모르겠다"]
WIDE = {"working": True}
NARROW = {"age_min": 19, "age_max": 34, "capital": True, "income_max_manwon": 1500}


def main() -> None:
    settings = load()
    db = Database(settings.db_path)
    auth.add_user(db, "smoke@x.go.kr")
    uid = db.one("SELECT id FROM users WHERE email='smoke@x.go.kr'")["id"]
    sid = "s_smoke"
    with db.tx() as con:
        con.execute("INSERT INTO surveys(id, user_id, title, policy_text, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                    (sid, uid, "저소득 근로자 소득 보전", POLICY, now(), now()))
    run, _ = jobs.submit(db, settings, uid, sid, QUESTION, OPTIONS, future=True)
    print("data", tmp, "| submitted", run["id"], "total", run["total"], "est_usd", run["estimate_usd"], flush=True)
    runner = jobs.JobRunner(db, settings)
    t0 = time.time()
    while True:
        claimed = runner._claim()
        if not claimed:
            break
        runner.run_one(*claimed)
    row = jobs.run_view(db.one("SELECT * FROM runs WHERE id=?", (run["id"],)))
    print("status", row["status"], row["error_code"], row["done"], "/", row["total"], "failed", row["failed"], f"{time.time() - t0:.0f}s")
    r = row["result"] or {}
    print("percent", r.get("percent"), "placebo", r.get("placebo_shift_pp"), "reversal", r.get("reversal_shift_pp"))
    print("future", json.dumps({k: r["future"][k] for k in ("n", "dead", "now_percent", "future_percent", "shift_pp", "format_shift_pp",
                                                             "threshold_pp", "distinguishable")}, ensure_ascii=False) if r.get("future") else None)
    if row["status"] != "succeeded" or not r.get("future"):
        return
    for label, rule in (("wide #1", WIDE), ("wide #2", WIDE), ("narrow", NARROW)):
        t = time.time()
        v = jobs.rule_view_for_run(db, uid, run["id"], rule)
        print(f"rule {label}: {time.time() - t:.3f}s | {v['rule_text']} | 2025 {v['y2025']} | 2030 {v['y2030']}")
        print("  main_split", json.dumps(v["main_split"], ensure_ascii=False), "|", v["main_small"])
        print("  future_split", json.dumps(v["future_split"], ensure_ascii=False))
        print("  lines:", *v["lines"], sep="\n    ")
    # four more add-on combinations must not evict the forecast cache (it lives apart from panel._cache)
    for combo in ("housing", "finance", "welfare", "work"):
        panel.load(addons=combo)
    t = time.time()
    jobs.rule_view_for_run(db, uid, run["id"], WIDE)
    print(f"rule after 4 add-on loads: {time.time() - t:.3f}s")


if __name__ == "__main__":
    main()
