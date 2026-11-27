"""심층 분석: after a survey run, the same respondents are heard one by one.

The survey (ppservice.survey) asks thousands of synthetic people one closed question. This job continues from that run
with the pp pipeline: a few hundred of the same respondents write their reasons in their own words, the reasons are
grouped into issues, checked on a larger part of the same panel, and turned into a draft hearing plan. Personas come
from the 20k bundle shipped with the service, so no external persona database is needed.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from .db import Database, now, today
from .settings import Settings
from .survey import panel
from .survey.run import Cancelled

log = logging.getLogger("ppservice.deep")
MAX_ATTEMPTS = 3
STAGES = ("segment", "clarity", "panel", "react", "issues", "jev", "alternatives", "review", "analyze", "hearing",
          "debrief", "plan")
STAGE_LABEL = {
    "segment": "정책 설명을 조항으로 나누는 중", "clarity": "문장이 쉬운지 살피는 중", "panel": "들을 사람을 고르는 중",
    "react": "한 사람씩 의견을 듣는 중", "issues": "의견을 쟁점으로 묶는 중", "jev": "더 많은 응답자에게 확인하는 중",
    "alternatives": "수정안을 견주는 중", "review": "답변을 점검하는 중", "analyze": "집계하는 중",
    "hearing": "가상 공청회를 여는 중", "debrief": "공청회 발언을 읽는 중", "plan": "의견수렴 계획서 초안을 쓰는 중",
}
STATUS_LABEL = {"queued": "접수됨", "running": "분석 중", "succeeded": "완료", "failed": "실패"}
ERROR_MESSAGES = {
    "llm_unavailable": "의견을 글로 쓰는 언어 모델에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    "model_unavailable": "응답 모델에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    "model_config": "분석에 필요한 자료나 설정이 서버에 없습니다. 운영자에게 알려 주세요.",
    "budget_exceeded": "실행 비용 또는 호출 한도에 도달해 중단했습니다.",
    "input_changed": "입력이 바뀌어 이전 결과를 이어 쓸 수 없습니다. 새 실행을 만들어 주세요.",
    "run_timeout": "분석이 제한 시간을 넘어 중단했습니다. 다시 시도하면 끝난 단계부터 이어서 합니다.",
    "server_restart": "서버가 여러 번 중단되어 분석을 마치지 못했습니다. 다시 시도해 주세요.",
    "invalid_result": "분석 결과가 점검을 통과하지 못해 보여 드리지 않습니다. 다시 시도해 주세요.",
    "internal": "처리 중 오류가 발생했습니다. 다시 시도해 주세요. 계속되면 운영자에게 알려 주세요.",
}
ESTIMATE_USD = 0.5  # reserved against the daily budget when a deep analysis is requested
VOICES_PER_OPTION = 6


class DeepError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class DeepFailed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def work_dir(settings: Settings, run_id: str) -> Path:
    return settings.data_dir / "deep-work" / run_id


def view(row, full: bool = True) -> dict:
    stage = row["stage"]
    return {
        "run_id": row["run_id"], "status": row["status"], "status_label": STATUS_LABEL.get(row["status"], row["status"]),
        "stage": stage, "stage_label": STAGE_LABEL.get(stage or "", ""),
        "stage_index": STAGES.index(stage) + 1 if stage in STAGES else 0, "stage_total": len(STAGES),
        "error_code": row["error_code"], "error_message": ERROR_MESSAGES.get(row["error_code"] or ""),
        "result": json.loads(row["result"]) if full and row["result"] else None,
        "created_at": row["created_at"], "started_at": row["started_at"], "finished_at": row["finished_at"],
    }


def _owned_run(db: Database, user_id: int, run_id: str):
    row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user_id))
    if not row:
        raise DeepError("not_found", "실행 기록을 찾을 수 없습니다.", 404)
    return row


def get(db: Database, user_id: int, run_id: str) -> dict | None:
    _owned_run(db, user_id, run_id)
    row = db.one("SELECT * FROM deeps WHERE run_id=?", (run_id,))
    return view(row) if row else None


def bundle(db: Database, user_id: int, run_id: str) -> dict:
    """The full pipeline bundle of a finished deep analysis (the data behind the summary)."""
    _owned_run(db, user_id, run_id)
    row = db.one("SELECT bundle FROM deeps WHERE run_id=? AND status='succeeded'", (run_id,))
    if not row or not row["bundle"]:
        raise DeepError("not_found", "심층 분석 결과가 없습니다.", 404)
    return json.loads(row["bundle"])


def request(db: Database, settings: Settings, user_id: int, run_id: str) -> tuple[dict, bool]:
    """Queue the deep analysis of a finished run. Returns (view, created); an active or finished one is returned as is,
    a failed one is queued again and resumes from its finished stages."""
    run = _owned_run(db, user_id, run_id)
    if run["status"] != "succeeded":
        raise DeepError("not_ready", "완료된 조사에서만 심층 분석을 할 수 있습니다.")
    with db.tx() as con:
        row = con.execute("SELECT * FROM deeps WHERE run_id=?", (run_id,)).fetchone()
        if row and row["status"] != "failed":
            return view(row), False
        n_today = con.execute("SELECT COUNT(*) FROM deeps WHERE user_id=? AND created_at>=?",
                              (user_id, today())).fetchone()[0]
        if not row and n_today >= settings.daily_deeps:
            raise DeepError("daily_limit", f"하루 심층 분석 횟수({settings.daily_deeps}회)를 모두 썼습니다. 내일 다시 시도해 주세요.", 429)
        spent = con.execute("SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0) FROM spend WHERE day=?",
                            (today(),)).fetchone()[0]
        reservation = con.execute("SELECT id, reserved_usd FROM spend WHERE run_id=? AND input_tokens=-1", (run_id,)).fetchone()
        cap = min(settings.max_cost_usd, ESTIMATE_USD)
        if not reservation and spent + cap > settings.daily_budget_usd:
            raise DeepError("budget_exceeded", "오늘 사용할 수 있는 실행 비용 한도에 도달했습니다. 내일 다시 시도해 주세요.", 429)
        if not reservation:
            # -1 identifies the deep-analysis reservation separately from the survey's batches.
            con.execute("INSERT INTO spend(run_id, user_id, day, reserved_usd, input_tokens, created_at)"
                        " VALUES (?, ?, ?, ?, -1, ?)", (run_id, user_id, today(), cap, now()))
        if row:
            con.execute("UPDATE deeps SET status='queued', attempt=0, error_code=NULL, error_detail=NULL, finished_at=NULL"
                        " WHERE run_id=?", (run_id,))
        else:
            con.execute("INSERT INTO deeps(run_id, user_id, status, created_at) VALUES (?, ?, 'queued', ?)",
                        (run_id, user_id, now()))
    return view(db.one("SELECT * FROM deeps WHERE run_id=?", (run_id,))), True


def recover(db: Database) -> int:
    n = 0
    with db.tx() as con:
        for row in con.execute("SELECT run_id, attempt FROM deeps WHERE status='running'").fetchall():
            n += 1
            if row["attempt"] >= MAX_ATTEMPTS:
                con.execute("UPDATE deeps SET status='failed', error_code='server_restart', finished_at=? WHERE run_id=?",
                            (now(), row["run_id"]))
            else:
                con.execute("UPDATE deeps SET status='queued' WHERE run_id=?", (row["run_id"],))
    return n


def claim(db: Database) -> tuple[str, int] | None:
    with db.tx() as con:
        row = con.execute("SELECT run_id FROM deeps WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if not row:
            return None
        if con.execute("UPDATE deeps SET status='running', attempt=attempt+1, started_at=?, stage=NULL"
                       " WHERE run_id=? AND status='queued'", (now(), row["run_id"])).rowcount == 0:
            return None
        return row["run_id"], con.execute("SELECT attempt FROM deeps WHERE run_id=?", (row["run_id"],)).fetchone()["attempt"]


def remove_work(settings: Settings, run_ids: list[str]) -> None:
    for run_id in run_ids:
        shutil.rmtree(work_dir(settings, run_id), ignore_errors=True)


def cleanup(db: Database, settings: Settings) -> int:
    """Remove working folders that no unfinished deep analysis owns (finished, deleted or expired runs)."""
    root = settings.data_dir / "deep-work"
    if not root.is_dir():
        return 0
    keep = {r["run_id"] for r in db.all("SELECT run_id FROM deeps WHERE status!='succeeded'")}
    gone = [p.name for p in root.iterdir() if p.is_dir() and p.name not in keep]
    remove_work(settings, gone)
    return len(gone)


def _choice(probs: list[float]) -> int:
    return max(range(len(probs)), key=lambda i: (probs[i], -i))


def _who(p: dict) -> dict:
    return {"name": "", "age": p["age"], "sex": p["sex"], "province": p["province"],
            "occupation": p["occupation"]}


def summarize(b: dict, spec: dict, main_answers: dict[str, list[float]]) -> dict:
    """The part of the pipeline bundle the result page shows, with every voice tied to the survey answer the same
    synthetic person gave. Reasons and suggestions are verbatim model output; nothing here is rewritten."""
    people = {p["uuid"]: p for p in b["personas"]}
    analysis, options = b["analysis"], spec["options"]
    groups: list[list[dict]] = [[] for _ in options]
    for r in b["reactions"]:
        probs, person = main_answers.get(r["uuid"]), people[r["uuid"]]
        if not probs or person["panel"] != "rep" or len(probs) != len(options):
            continue
        k = _choice(probs)
        groups[k].append({"rid": r["rid"], **_who(person), "reason": r["reason"], "support": r["support"],
                          "p": round(probs[k], 3)})
    heard = sum(len(g) for g in groups)
    by_option = []
    for option, voices in zip(options, groups):
        voices.sort(key=lambda v: (-v["p"], v["rid"]))
        by_option.append({
            "option": option, "n": len(voices), "share": round(len(voices) / heard, 4) if heard else 0.0,
            "mean_support": round(sum(v["support"] for v in voices) / len(voices), 2) if voices else None,
            "voices": voices[:VOICES_PER_OPTION]})
    by_rid = {r["rid"]: r for r in b["reactions"]}

    def quote(q: dict) -> dict:
        return {"text": q["text"], **_who(people[by_rid[q["rid"]]["uuid"]])}

    issues = [{"id": it["id"], "title": it["title"], "stance": it["stance"], "summary": it["summary"], "n": it["n"],
               "share": it["share"], "mean": it["mean"], "jev_mean": it.get("jev_mean"),
               "by_panel": it.get("by_panel"), "basis": "rep",
               "quotes": [quote(q) for q in it["quotes"][:2]]}
              for it in sorted(analysis["issues"], key=lambda it: -it["n"])[:6]]
    outreach = [{"kind": o["kind"], "group": o["group"], "n": o["n"], "direct": o["direct"], "oppose": o["oppose"],
                 "silent": o["silent"], "channels": o.get("channels", [])[:3], "suggestion": o["suggestion"],
                 "panel": o.get("panel"), "caution": o.get("caution")}
                for o in analysis["outreach"][:5]]
    alternatives = [{"title": a["title"], "text": a["text"], "source_example": a["source_example"], "n": a["n"],
                     "d_favor": a["d_favor"], "net_favor": a.get("net_favor")}
                    for a in (analysis.get("alternatives") or {}).get("items", [])]
    meta = b["meta"]
    counts = meta.get("counts", {})
    coverage = [_coverage("한 사람씩 의견 듣기", counts.get("react_calls"), counts.get("reactions")),
                _coverage("더 많은 응답자에게 확인", counts.get("jev_calls"), counts.get("jev_scored"))]
    cost = sum(u.get("cost_usd", 0) for stage in (meta.get("jev_usage") or {}).values() for u in stage.values())
    ledger = meta.get("budget")
    if ledger:
        cost = ledger["cost_usd"]
    return {
        "mock": meta.get("provider") == "mock", "models": meta.get("models", {}),
        "counts": {"heard": len(b["reactions"]), "matched": heard,
                   "representative": b["panel"]["representative"]["n"], "affected": b["panel"]["affected"]["n"],
                   "checked": (analysis.get("jev") or {}).get("n", 0)},
        "overall": analysis["overall"], "overall_aff": analysis.get("overall_aff"),
        "panel_caution": "영향권: 전체 비율로 읽지 않음", "panel_version": meta.get("panel_version"),
        "source_revision": meta.get("source_revision"), "by_option": by_option, "issues": issues, "outreach": outreach,
        "alternatives": alternatives, "insights": analysis.get("insights", []),
        "hearing": {"agenda": b["hearing"]["agenda"], "summary": b["hearing"]["summary"],
                    "turns": len(b["hearing"]["turns"]), "participants": len(b["hearing"]["participants"])},
        "qa": [{"question": q["question"], "answer": q["answer"]} for q in b["plan"]["qa"][:5]],
        "limits": b["plan"]["limits"], "fallbacks": meta.get("fallbacks", []),
        "coverage": [c for c in coverage if c],
        "seconds": round(sum(s["seconds"] for s in meta.get("stages", [])), 1),
        "cost_usd": round(cost, 4) if cost is not None else None,
        "cost_status": ledger.get("cost_status") if ledger else "legacy_partial",
        "budget": ledger,
    }


def _coverage(step: str, planned, done) -> dict | None:
    """Planned versus answered calls for one step. A step whose calls failed is "실행 안 됨", never "없음"."""
    if not planned:
        return None
    done = done or 0
    status = "완료" if done >= planned else ("일부" if done else "실행 안 됨")
    return {"step": step, "planned": planned, "done": done, "status": status}


def _classify(e: Exception) -> str:
    from pp import budget, config, jev, llm, provenance

    if isinstance(e, budget.BudgetExceeded):
        return "budget_exceeded"
    if isinstance(e, provenance.InputMismatch):
        return "input_changed"

    if isinstance(e, llm.LLMError):
        return "llm_unavailable"
    if isinstance(e, jev.JevError):
        return "model_unavailable"
    if isinstance(e, config.DataMissing):
        return "model_config"
    return "internal"


def run_one(db: Database, settings: Settings, run_id: str, attempt: int, stop: threading.Event | None = None) -> None:
    from pp import budget, export, llm, pipeline

    from .jobs import _answers, scrub

    stop = stop or threading.Event()
    run = db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run:
        return
    spec = json.loads(run["spec"])
    started = time.monotonic()

    def fenced(sql: str, args: tuple) -> int:
        """`sql` ends with "WHERE run_id=? AND attempt=?" so a stale attempt changes nothing."""
        with db.tx() as con:
            return con.execute(sql, (*args, run_id, attempt)).rowcount

    def on_stage(name: str) -> None:
        if stop.is_set():
            raise Cancelled()
        if time.monotonic() - started > settings.deep_timeout:
            raise DeepFailed("run_timeout")
        if fenced("UPDATE deeps SET stage=? WHERE run_id=? AND attempt=?", (name,)) == 0:  # deleted, or claimed again by a newer attempt
            raise Cancelled()

    # The service hears the people of its own panel bundle; the embedding search belongs to the 1M-person database.
    os.environ["PP_PERSONA_SOURCE"] = "bundle"
    os.environ["PP_SEMANTIC"] = "off"
    folder = work_dir(settings, run_id)
    try:
        people_all, panel_version = panel.load(addons="off")
        from pp import provenance

        data_meta = {**provenance.artifact(panel.BUNDLE, compressed=True), "panel_version": panel_version,
                     "persona_source": "bundle"}
        pool = [p["uuid"] for p in panel.sample(people_all, spec["n"], spec["seed"])]
        folder.mkdir(parents=True, exist_ok=True)
        policy_path = folder / "policy.in.json"
        policy_path.write_text(json.dumps({"id": run_id, "title": spec["title"], "kind": "현장 질문 미리 설계",
                                           "agency": "", "source": {"note": "현장 질문 미리 설계에서 이어진 심층 분석"},
                                           "text": spec["policy_text"]}, ensure_ascii=False), encoding="utf-8")
        mock = llm.provider() == "mock"
        kwargs = dict(n_rep=settings.deep_rep, n_aff=settings.deep_aff, n_jev=settings.deep_jev, n_alt=settings.deep_alt,
                      workers=settings.deep_workers, seed=spec["seed"] % 100_000, allow_mock=mock, run_dir=folder,
                      pool_uuids=pool, on_stage=on_stage, data_meta=data_meta,
                      limits=budget.Limits(settings.max_calls, settings.max_output_tokens, settings.max_retries,
                                           settings.max_concurrency, min(settings.max_cost_usd, ESTIMATE_USD)))
        job = pipeline.Run(policy_path, **kwargs)
        job.run(skip=("export",))
        full = export.assemble(folder)
        errors = export.validate_bundle(full, allow_mock=mock)
        if errors:
            raise DeepFailed("invalid_result", "; ".join(errors[:3]))
        result = summarize(full, spec, _answers(db, run_id).get("main", {}))
    except Cancelled:
        log.info("deep=%s attempt=%s cancelled", run_id, attempt)
        return
    except DeepFailed as e:
        log.warning("deep=%s attempt=%s failed code=%s", run_id, attempt, e.code)
        fenced("UPDATE deeps SET status='failed', error_code=?, error_detail=?, finished_at=? WHERE run_id=? AND attempt=?",
               (e.code, scrub(e.detail, spec["policy_text"]), now()))
        return
    except Exception as e:  # noqa: BLE001
        code = _classify(e)
        log.exception("deep=%s attempt=%s %s %s", run_id, attempt, code, type(e).__name__)
        fenced("UPDATE deeps SET status='failed', error_code=?, error_detail=?, finished_at=? WHERE run_id=? AND attempt=?",
               (code, scrub(f"{type(e).__name__}: {e}", spec["policy_text"]), now()))
        return
    try:
        with db.tx() as con:
            done = con.execute("UPDATE deeps SET status='succeeded', stage=NULL, result=?, bundle=?, finished_at=?"
                               " WHERE run_id=? AND attempt=?",
                               (json.dumps(result, ensure_ascii=False), json.dumps(full, ensure_ascii=False), now(),
                                run_id, attempt)).rowcount
            if done:
                if result.get("cost_status") == "known":
                    con.execute("UPDATE spend SET actual_usd=? WHERE run_id=? AND input_tokens=-1",
                                (result["cost_usd"], run_id))
    except sqlite3.Error:
        log.exception("deep=%s attempt=%s could not store the result", run_id, attempt)
        return
    shutil.rmtree(folder, ignore_errors=True)
    log.info("deep=%s attempt=%s succeeded secs=%.1f", run_id, attempt, time.monotonic() - started)
