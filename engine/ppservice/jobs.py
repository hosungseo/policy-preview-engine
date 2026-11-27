"""Run intake, the in-process runner, cost reservation, recovery and retry."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from pp.filelock_util import lock_file, unlock_file
from pp import budget, provenance, jev

from . import deep
from .db import Database, now, today
from .settings import Settings, jev_price_per_m_input
from .survey import aggregate, lint, panel, visit
from .survey.run import ARMS, FUTURE_ARMS, Cancelled, RunFailed, estimate_tokens, execute

log = logging.getLogger("ppservice.jobs")
MAX_ATTEMPTS = 3
_visit_cache: dict[str, dict] = {}
_visit_lock = threading.Lock()

ERROR_MESSAGES = {
    "input_changed": "입력이 바뀌어 이전 결과를 이어 쓸 수 없습니다. 새 실행을 만들어 주세요.",
    "model_unavailable": "응답 모델(Jev)에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.",
    "too_many_failures": "응답을 받지 못한 합성 인물이 너무 많아 결과를 만들지 않았습니다. 다시 시도해 주세요.",
    "model_config": "응답 모델 설정에 문제가 있습니다. 운영자에게 알려 주세요.",
    "budget_exceeded": "오늘 사용할 수 있는 실행 비용 한도에 도달했습니다. 내일 다시 시도해 주세요.",
    "run_timeout": "실행이 제한 시간(30분)을 넘어 중단했습니다. 다시 시도하면 받은 응답부터 이어서 합니다.",
    "server_restart": "서버가 여러 번 중단되어 실행을 마치지 못했습니다. 다시 시도해 주세요.",
    "internal": "처리 중 오류가 발생했습니다. 다시 시도해 주세요. 계속되면 운영자에게 알려 주세요.",
}
STATUS_LABEL = {"queued": "접수됨", "running": "응답 받는 중", "succeeded": "완료", "failed": "실패"}


class IntakeError(Exception):
    def __init__(self, code: str, message: str, status: int = 429, findings: list | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.findings = code, message, status, findings


def scrub(detail: str, text: str) -> str:
    out = detail or ""
    for chunk in set(re.findall(r"\S[^\n]{7,}", text or "")):
        if chunk in out:
            out = out.replace(chunk, "[원문 생략]")
    return out[:300]


def day_start() -> str:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def run_view(row) -> dict:
    return {
        "id": row["id"], "survey_id": row["survey_id"], "status": row["status"],
        "status_label": STATUS_LABEL.get(row["status"], row["status"]), "spec": json.loads(row["spec"]),
        "lint": json.loads(row["lint"]), "done": row["done"], "total": row["total"], "failed": row["failed"],
        "error_code": row["error_code"], "error_message": ERROR_MESSAGES.get(row["error_code"] or ""),
        "result": json.loads(row["result"]) if row["result"] else None, "retry_of": row["retry_of"],
        "panel_version": row["panel_version"], "jev_model": row["jev_model"], "estimate_usd": row["estimate_usd"],
        "created_at": row["created_at"], "started_at": row["started_at"], "finished_at": row["finished_at"],
    }


def arm_count(spec: dict) -> int:
    return len(ARMS) + (len(FUTURE_ARMS) if spec.get("future") else 0)


def estimate_usd(spec: dict, n: int) -> float:
    addons = panel.addons_setting(panel.spec_text(spec))
    profile_chars = 1300 + 25 * len(addons) + (60 if addons else 0)  # + add-on lines (~325 chars for all 13)
    profile_chars += 200 if spec.get("future") else 0  # the state block of the "5년 뒤 보기" arms
    return round(arm_count(spec) * n * estimate_tokens(spec, profile_chars) * jev_price_per_m_input() / 1e6, 3)


def submit(db: Database, settings: Settings, user_id: int, survey_id: str, question: str, options: list[str],
           retry_of: str | None = None, future: bool = False) -> tuple[dict, bool]:
    survey = db.one("SELECT * FROM surveys WHERE id=? AND user_id=?", (survey_id, user_id))
    if not survey:
        raise IntakeError("not_found", "미리보기를 찾을 수 없습니다.", 404)
    question = (question or "").strip()
    options = [o.strip() for o in options if o and o.strip()]
    problems = []
    if not question:
        problems.append("문항을 입력해 주세요.")
    if len(question) > settings.max_question:
        problems.append(f"문항은 {settings.max_question}자 이내로 써 주세요.")
    if any(len(o) > settings.max_option for o in options):
        problems.append(f"선택지는 각각 {settings.max_option}자 이내로 써 주세요.")
    findings = lint.check(survey["policy_text"], question, options)
    if future and not panel.future_available():
        problems.append("5년 뒤 보기 자료가 서버에 준비되지 않았습니다.")
    if problems or lint.blocked(findings):
        msg = " ".join(problems + [f["message"] for f in findings if f["level"] == "block"])
        raise IntakeError("invalid_question", msg, 422, findings)
    active = db.one("SELECT * FROM runs WHERE survey_id=? AND status IN ('queued','running')", (survey_id,))
    if active:
        return run_view(active), False
    spec = {"title": survey["title"], "policy_text": survey["policy_text"], "question": question, "options": options,
            "n": settings.n, "seed": int(hashlib.sha256(survey_id.encode()).hexdigest()[:8], 16)}
    if future:
        spec["future"] = True
    est = estimate_usd(spec, settings.n)
    with db.tx() as con:
        n_today = con.execute("SELECT COUNT(*) FROM runs WHERE user_id=? AND created_at>=?", (user_id, day_start())).fetchone()[0]
        if n_today >= settings.daily_runs:
            raise IntakeError("daily_limit", f"하루 실행 횟수({settings.daily_runs}회)를 모두 썼습니다. 내일 다시 시도해 주세요.")
        spent = con.execute("SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0) FROM spend WHERE day=?", (today(),)).fetchone()[0]
        if spent + est > settings.daily_budget_usd:
            raise IntakeError("budget_exceeded", ERROR_MESSAGES["budget_exceeded"])
        run_id = "u_" + secrets.token_hex(8)
        try:
            con.execute("INSERT INTO runs(id, survey_id, user_id, status, spec, spec_hash, lint, retry_of, total, estimate_usd, created_at)"
                        " VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, survey_id, user_id, json.dumps(spec, ensure_ascii=False), spec_hash(spec),
                         json.dumps(findings, ensure_ascii=False), retry_of, arm_count(spec) * settings.n, est, now()))
            con.execute("UPDATE surveys SET updated_at=? WHERE id=?", (now(), survey_id))
            created = True
        except sqlite3.IntegrityError:
            created = False
    row = db.one("SELECT * FROM runs WHERE id=?", (run_id,)) if created else \
        db.one("SELECT * FROM runs WHERE survey_id=? AND status IN ('queued','running')", (survey_id,))
    return run_view(row), created


def retry(db: Database, settings: Settings, user_id: int, run_id: str) -> dict:
    row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user_id))
    if not row:
        raise IntakeError("not_found", "실행 기록을 찾을 수 없습니다.", 404)
    if row["status"] != "failed":
        raise IntakeError("not_failed", "실패한 실행만 다시 시도할 수 있습니다.", 409)
    spec = json.loads(row["spec"])
    # Carry the run's flags: without `future` the retry would become a plain run with a different spec_hash, and
    # the answers already paid for would not be reused.
    run, _ = submit(db, settings, user_id, row["survey_id"], spec["question"], spec["options"], retry_of=run_id,
                    future=bool(spec.get("future")))
    return run


RULE_INTS = (("income_max_manwon", 0, 100_000, "소득 상한"), ("income_min_manwon", 0, 100_000, "소득 하한"),
             ("age_min", 19, 110, "나이 하한"), ("age_max", 19, 110, "나이 상한"))
NOTE_MAX = 200


def validate_rule(rule: dict) -> dict:
    """The normalized rule (every key present, absent axes None) or IntakeError 422. Messages name axes only, never
    the values typed in."""
    from pp import life_history as lh

    out = {key: rule.get(key) for key in lh.RULE_KEYS}
    problems = []
    for key, lo, hi, label in RULE_INTS:
        v = out[key]
        if v is None:
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v:
            problems.append(f"{label}은 정수(만 원·세)로 적어 주세요.")
            out[key] = None
            continue
        out[key] = int(v)
        if not lo <= out[key] <= hi:
            problems.append(f"{label}은 {lo:,}~{hi:,} 사이여야 합니다.")
    if out["income_min_manwon"] is not None and out["income_max_manwon"] is not None and out["income_min_manwon"] > out["income_max_manwon"]:
        problems.append("소득 하한이 상한보다 큽니다.")
    if out["age_min"] is not None and out["age_max"] is not None and out["age_min"] > out["age_max"]:
        problems.append("나이 하한이 상한보다 큽니다.")
    for key in ("working", "capital"):
        if out[key] is not None and not isinstance(out[key], bool):
            problems.append(f"{'일함 여부' if key == 'working' else '수도권 여부'}는 예/아니요/상관없음 중 하나여야 합니다.")
            out[key] = None
    out["note"] = (out["note"] or "").strip() if isinstance(out["note"], str) else ""
    if len(out["note"]) > NOTE_MAX:
        problems.append(f"메모는 {NOTE_MAX}자 이내로 써 주세요.")
    if all(out[key] is None for key in lh.RULE_KEYS if key != "note"):
        problems.append("소득·일함·나이·수도권 중 하나는 적어 주세요.")
    if problems:
        raise IntakeError("invalid_rule", " ".join(problems), 422)
    return out


def _answers(db: Database, run_id: str) -> dict[str, dict[str, list[float]]]:
    answers: dict[str, dict[str, list[float]]] = {}
    for a in db.all("SELECT arm, uuid, probs FROM answers WHERE run_id=?", (run_id,)):
        answers.setdefault(a["arm"], {})[a["uuid"]] = json.loads(a["probs"])
    return answers


def visit_view_for_run(db: Database, user_id: int, run_id: str) -> dict:
    """「찾아갈 곳」 for a finished run, computed from its stored answers on request (survey/visit.py). Read-only."""
    row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user_id))
    if not row:
        raise IntakeError("not_found", "실행 기록을 찾을 수 없습니다.", 404)
    spec, result = json.loads(row["spec"]), json.loads(row["result"] or "null")
    if row["status"] != "succeeded" or not result:
        raise IntakeError("not_applicable", "완료된 실행에서만 볼 수 있습니다.", 409)
    with _visit_lock:
        if run_id not in _visit_cache:  # a finished run's answers never change
            people_all, _ = panel.load(addons="off")
            people = panel.sample(people_all, spec["n"], spec["seed"])
            while len(_visit_cache) >= 32:
                _visit_cache.pop(next(iter(_visit_cache)))
            _visit_cache[run_id] = visit.view(spec, people, _answers(db, run_id), result["options"], row["panel_version"],
                                              everyone=people_all)
        return _visit_cache[run_id]


def rule_view_for_run(db: Database, user_id: int, run_id: str, rule: dict) -> dict:
    """"대상 규칙으로 나눠 보기": split a finished "5년 뒤 보기" run's stored answers by a rule. Read-only; the order of
    checks is fixed."""
    row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user_id))
    if not row:
        raise IntakeError("not_found", "실행 기록을 찾을 수 없습니다.", 404)
    spec, result = json.loads(row["spec"]), json.loads(row["result"] or "null")
    if row["status"] != "succeeded" or not spec.get("future") or not (result or {}).get("future"):
        raise IntakeError("not_applicable", "이 실행에는 적용할 수 없습니다. 5년 뒤 보기를 켠 완료된 실행에서만 쓸 수 있습니다.", 409)
    if not panel.future_available():
        raise IntakeError("future_unavailable", "5년 뒤 보기 자료가 서버에 준비되지 않았습니다.", 422)
    rule = validate_rule(rule)
    _, _, version = panel._future_rows()
    if result["future"].get("version") != version:
        raise IntakeError("data_changed", "자료가 바뀌어 이 실행에는 규칙을 적용할 수 없습니다.", 409)
    people_all, _ = panel.load(addons="off")
    people = panel.sample(people_all, spec["n"], spec["seed"])
    states = panel.states(people)
    view = aggregate.rule_view(people, _answers(db, run_id), len(result["options"]), result["top"], rule, states,
                               max(result["placebo_shift_pp"], result["reversal_shift_pp"]),
                               result["future"]["format_shift_pp"], top_label=result["options"][result["top"]])
    log.info("run=%s rule view in2025=%s in2030=%s", run_id, view["y2025"]["n"], view["y2030"]["n"])
    return view


class Runner:
    """Per-run context. Writes are fenced by (id, attempt); answers are idempotent per (arm, uuid)."""

    def __init__(self, db: Database, settings: Settings, run_id: str, attempt: int, user_id: int, stop: threading.Event):
        self.db, self.settings, self.run_id, self.attempt, self.user_id, self.stop = db, settings, run_id, attempt, user_id, stop
        self.started = time.monotonic()
        self._lock = threading.Lock()
        ledger_dir = settings.data_dir / "run-limits"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        self.budget = budget.Budget(budget.Limits(settings.max_calls, settings.max_output_tokens,
            settings.max_retries, settings.max_concurrency, settings.max_cost_usd), ledger_dir / f"{run_id}.json")

    def _fenced(self, sql: str, args: tuple) -> int:
        with self.db.tx() as con:
            return con.execute(sql, (*args, self.run_id, self.attempt)).rowcount

    def check_alive(self) -> None:
        if self.stop.is_set():
            raise Cancelled()
        if time.monotonic() - self.started > self.settings.run_timeout:
            raise RunFailed("run_timeout")
        row = self.db.one("SELECT status, attempt FROM runs WHERE id=?", (self.run_id,))
        if not row or row["status"] != "running" or row["attempt"] != self.attempt:
            raise Cancelled()

    def call_timeout(self) -> float:
        return max(5.0, min(60.0, self.settings.run_timeout - (time.monotonic() - self.started)))

    def sleep(self, seconds: float) -> None:
        if self.stop.wait(seconds):
            raise Cancelled()

    def done_keys(self) -> set[tuple[str, str]]:
        return {(r["arm"], r["uuid"]) for r in self.db.all("SELECT arm, uuid FROM answers WHERE run_id=?", (self.run_id,))}

    def save_answer(self, arm: str, uuid: str, probs: list[float], tokens: int) -> None:
        with self.db.tx() as con:
            con.execute("INSERT OR IGNORE INTO answers(run_id, arm, uuid, probs, input_tokens) VALUES (?, ?, ?, ?, ?)",
                        (self.run_id, arm, uuid, json.dumps(probs), tokens))

    def progress(self) -> None:
        with self.db.tx() as con:
            done = con.execute("SELECT COUNT(*) FROM answers WHERE run_id=?", (self.run_id,)).fetchone()[0]
            con.execute("UPDATE runs SET done=? WHERE id=? AND attempt=?", (done, self.run_id, self.attempt))

    def reserve(self, calls: int, tokens_each: int) -> int:
        worst = calls * tokens_each * 1.5 * jev_price_per_m_input() / 1e6
        with self.db.tx() as con:
            spent = con.execute("SELECT COALESCE(SUM(COALESCE(actual_usd, reserved_usd)), 0) FROM spend WHERE day=?",
                                (today(),)).fetchone()[0]
            if spent + worst > self.settings.daily_budget_usd:
                raise RunFailed("budget_exceeded", f"{spent:.2f}+{worst:.2f}")
            return con.execute("INSERT INTO spend(run_id, user_id, day, reserved_usd, created_at) VALUES (?, ?, ?, ?, ?)",
                               (self.run_id, self.user_id, today(), worst, now())).lastrowid

    def settle(self, reservation: int, tokens: int) -> None:
        with self.db.tx() as con:
            con.execute("UPDATE spend SET actual_usd=?, input_tokens=? WHERE id=?",
                        (round(tokens * jev_price_per_m_input() / 1e6, 6), tokens, reservation))


def default_evaluate(settings: Settings) -> Callable:
    import os

    from pp import jev
    if settings.jev_provider == "fail":  # failure drill: every call fails without touching the network
        def fail(*args, **kwargs):
            raise jev.JevError("drill: PP_JEV_PROVIDER=fail")
        return fail
    os.environ["PP_JEV_PROVIDER"] = settings.jev_provider
    return jev.evaluate


class JobRunner:
    def __init__(self, db: Database, settings: Settings, evaluate: Callable | None = None):
        self.db, self.settings = db, settings
        self.evaluate = evaluate or default_evaluate(settings)
        self.wake, self.stop, self.deep_wake = threading.Event(), threading.Event(), threading.Event()
        self.threads: list[threading.Thread] = []
        self._lock_file = None

    def acquire_lock(self) -> None:
        self._lock_file = open(self.settings.lock_path, "w+")
        try:
            lock_file(self._lock_file, nonblocking=True)
        except OSError as e:
            self._lock_file.close()
            self._lock_file = None
            raise SystemExit("다른 ppservice 프로세스가 이미 실행 중입니다(잠금 파일 사용 중).") from e

    def recover(self) -> int:
        n = 0
        with self.db.tx() as con:
            for row in con.execute("SELECT id, attempt FROM runs WHERE status='running'").fetchall():
                n += 1
                if row["attempt"] >= MAX_ATTEMPTS:
                    con.execute("UPDATE runs SET status='failed', error_code='server_restart', finished_at=? WHERE id=?", (now(), row["id"]))
                else:
                    con.execute("UPDATE runs SET status='queued' WHERE id=?", (row["id"],))
        return n + deep.recover(self.db)

    def start(self) -> None:
        for i in range(self.settings.workers):
            t = threading.Thread(target=self._loop, name=f"ppservice-worker-{i}", daemon=True)
            t.start()
            self.threads.append(t)
        # Deep analyses take minutes; one thread of their own keeps them from holding up surveys.
        t = threading.Thread(target=self._deep_loop, name="ppservice-deep", daemon=True)
        t.start()
        self.threads.append(t)

    def _deep_loop(self) -> None:
        while not self.stop.is_set():
            try:
                claimed = deep.claim(self.db)
            except sqlite3.OperationalError:
                claimed = None
            if not claimed:
                self.deep_wake.wait(1.0)
                self.deep_wake.clear()
                continue
            deep.run_one(self.db, self.settings, *claimed, stop=self.stop)

    def shutdown(self) -> None:
        self.stop.set()
        self.wake.set()
        self.deep_wake.set()
        for t in self.threads:
            t.join(timeout=5)
        if self._lock_file is not None:
            unlock_file(self._lock_file)
            self._lock_file.close()
            self._lock_file = None

    def _claim(self) -> tuple[str, int] | None:
        with self.db.tx() as con:
            row = con.execute("SELECT id FROM runs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if not row:
                return None
            if con.execute("UPDATE runs SET status='running', attempt=attempt+1, started_at=? WHERE id=? AND status='queued'",
                           (now(), row["id"])).rowcount == 0:
                return None
            return row["id"], con.execute("SELECT attempt FROM runs WHERE id=?", (row["id"],)).fetchone()["attempt"]

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                claimed = self._claim()
            except sqlite3.OperationalError:
                claimed = None
            if not claimed:
                self.wake.wait(1.0)
                self.wake.clear()
                continue
            self.run_one(*claimed)

    def run_one(self, run_id: str, attempt: int) -> None:
        row = self.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not row:
            return
        spec = json.loads(row["spec"])
        runner = Runner(self.db, self.settings, run_id, attempt, row["user_id"], self.stop)
        t0 = time.monotonic()
        try:
            people_all, version = panel.load(addons=panel.addons_setting(panel.spec_text(spec)) or "off")
            people = panel.sample(people_all, spec["n"], spec["seed"])
            runner._fenced("UPDATE runs SET panel_version=? WHERE id=? AND attempt=?", (version,))
            extra, future_meta = {}, None
            if spec.get("future"):
                base_people, future_people, future_meta = panel.future_pair(people)
                extra = dict(zip(FUTURE_ARMS, (base_people, future_people)))
                runner._fenced("UPDATE runs SET total=? WHERE id=? AND attempt=?",
                               (len(ARMS) * len(people) + 2 * len(future_people),))
            identity = provenance.input_hash({"spec": spec, "people": people, "extra": extra,
                "panel_version": version, "model": jev.model(), "provider": self.settings.jev_provider,
                "endpoint": provenance.input_hash(jev.api_url()), "code": provenance.code_version()})
            identity_path = self.settings.data_dir / "run-limits" / f"{run_id}.inputs.json"
            if identity_path.exists():
                if json.loads(identity_path.read_text())["input_hash"] != identity:
                    raise RunFailed("input_changed")
            elif runner.done_keys():
                raise RunFailed("input_changed", "legacy partial answers have no input identity")
            identity_path.write_text(json.dumps({"input_hash": identity}), encoding="utf-8")
            if row["retry_of"]:
                old_path = identity_path.with_name(f"{row['retry_of']}.inputs.json")
                if old_path.exists() and json.loads(old_path.read_text()).get("input_hash") == identity:
                    self._reuse(row["retry_of"], run_id, row["spec_hash"])
            with runner.budget.scope():
                outcome = execute(runner, spec, people, self.evaluate, self.settings.threads, extra=extra)
            answers: dict[str, dict[str, list[float]]] = {}
            for a in self.db.all("SELECT arm, uuid, probs FROM answers WHERE run_id=?", (run_id,)):
                answers.setdefault(a["arm"], {})[a["uuid"]] = json.loads(a["probs"])
            result = aggregate.summarize(spec, people, answers, json.loads(row["lint"]),
                                         panel_version=version, model_version=outcome["model"], future=future_meta)
            result.update(input_hash=identity, budget=runner.budget.snapshot())
        except Cancelled:
            log.info("run=%s attempt=%s cancelled", run_id, attempt)
            return
        except RunFailed as e:
            log.warning("run=%s attempt=%s failed code=%s", run_id, attempt, e.code)
            runner._fenced("UPDATE runs SET status='failed', error_code=?, error_detail=?, finished_at=? WHERE id=? AND attempt=?",
                           (e.code, scrub(e.detail, spec["policy_text"]), now()))
            runner.progress()
            return
        except Exception as e:
            log.exception("run=%s attempt=%s internal %s", run_id, attempt, type(e).__name__)
            runner._fenced("UPDATE runs SET status='failed', error_code='internal', error_detail=?, finished_at=?"
                           " WHERE id=? AND attempt=?",
                           (scrub(f"{type(e).__name__}: {e}", spec["policy_text"]), now()))
            return
        runner.progress()
        runner._fenced("UPDATE runs SET status='succeeded', failed=?, jev_model=?, result=?, finished_at=?"
                       " WHERE id=? AND attempt=?",
                       (outcome["failed"], outcome["model"], json.dumps(result, ensure_ascii=False), now()))
        log.info("run=%s attempt=%s succeeded secs=%.1f failed=%s", run_id, attempt, time.monotonic() - t0, outcome["failed"])

    def _reuse(self, old_id: str, new_id: str, new_hash: str) -> None:
        """A retry with the same spec keeps the answers already paid for."""
        old = self.db.one("SELECT spec_hash FROM runs WHERE id=?", (old_id,))
        if old and old["spec_hash"] == new_hash:
            with self.db.tx() as con:
                con.execute("INSERT OR IGNORE INTO answers(run_id, arm, uuid, probs, input_tokens)"
                            " SELECT ?, arm, uuid, probs, 0 FROM answers WHERE run_id=?", (new_id, old_id))


def cleanup(db: Database, settings: Settings) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=settings.retention_days)).isoformat(timespec="seconds")
    with db.tx() as con:
        surveys = con.execute("DELETE FROM surveys WHERE updated_at<?", (cutoff,)).rowcount
        sessions = con.execute("DELETE FROM sessions WHERE expires_at<?", (now(),)).rowcount
        con.execute("DELETE FROM login_attempts WHERE at<?",
                    ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds"),))
    db.checkpoint()
    return {"surveys": surveys, "sessions": sessions, "deep_work": deep.cleanup(db, settings)}


def reaggregate(db: Database) -> int:
    """Recompute finished results from stored answers after the aggregation code changes."""
    people_all, _ = panel.load(addons="off")  # aggregation reads only the base attributes
    n = 0
    for row in db.all("SELECT * FROM runs WHERE status='succeeded'"):
        spec = json.loads(row["spec"])
        people = panel.sample(people_all, spec["n"], spec["seed"])
        answers: dict[str, dict[str, list[float]]] = {}
        for a in db.all("SELECT arm, uuid, probs FROM answers WHERE run_id=?", (row["id"],)):
            answers.setdefault(a["arm"], {})[a["uuid"]] = json.loads(a["probs"])
        future_meta = panel.future_pair(people)[2] if spec.get("future") and panel.future_available() else None
        result = aggregate.summarize(spec, people, answers, json.loads(row["lint"]), aggregate.load_baseline(),
                                     future=future_meta)
        # Reaggregation must not graft today's diagnostic onto historical runs.
        old_result = json.loads(row["result"] or '{}')
        old_accuracy = old_result.get('accuracy')
        if old_accuracy:
            result['accuracy'] = old_accuracy
            if old_accuracy.get('payload', {}).get('historical_baseline'):
                result['summary_text'] = old_result['summary_text']
                result['cautions'] = old_result.get('cautions', [])
        if row["panel_version"] and "+addons-" in row["panel_version"] and not result.get("addons"):
            # the run's own add-ons, from its recorded panel version
            result["addons"] = aggregate.addons_view(row["panel_version"])
            result["cautions"] = old_result.get("cautions", result["cautions"])
        if result.get("future") and (old_result.get("future") or {}).get("version"):
            # the answers were given against the forecast of that time; keep its version so a rebuilt forecast is noticed
            result["future"]["version"] = old_result["future"]["version"]
        with db.tx() as con:
            con.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result, ensure_ascii=False), row["id"]))
        n += 1
    return n
