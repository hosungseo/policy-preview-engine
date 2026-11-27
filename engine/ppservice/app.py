"""FastAPI app: JSON API under /api, the static web build at /."""
from __future__ import annotations

import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pp import config as pp_config, jev, lawmaking, llm

from . import auth, deep, jobs, profile
from .db import Database, now
from .settings import REPO_ROOT, Settings, load
from .survey import aggregate, lint, panel

log = logging.getLogger("ppservice.app")
COOKIE = "pp_session"
CLIENT_HEADER = "x-pp-client"


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, findings: list | None = None):
        detail = {"code": code, "message": message}
        if findings is not None:
            detail["findings"] = findings
        super().__init__(status_code=status, detail=detail)


class LoginBody(BaseModel):
    email: str
    code: str


class SurveyBody(BaseModel):
    title: str
    policy_text: str


class QuestionBody(BaseModel):
    question: str
    options: list[str]
    future: bool = False  # also ask the same people in their projected 2030 state ("5년 뒤 보기")


class LintBody(QuestionBody):
    policy_text: str = ""


class DesignBody(BaseModel):
    title: str = ""
    policy_text: str


class RuleBody(BaseModel):
    """"대상 규칙으로 나눠 보기": who a policy is for, judged on each member's 2025 and projected 2030 state."""
    income_max_manwon: int | None = None
    income_min_manwon: int | None = None
    working: bool | None = None
    age_min: int | None = None
    age_max: int | None = None
    capital: bool | None = None
    note: str = ""


def create_app(settings: Settings | None = None, start_workers: bool = True, evaluate: Callable | None = None) -> FastAPI:
    settings = settings or load()
    db = Database(settings.db_path)
    runner = jobs.JobRunner(db, settings, evaluate)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_workers:
            runner.acquire_lock()
            recovered = runner.recover()
            removed = jobs.cleanup(db, settings)
            log.info("startup jev=%s n=%s recovered=%s cleanup=%s", settings.jev_provider, settings.n, recovered, removed)
            if not panel.BUNDLE.exists():
                log.warning("합성 인물 패널 파일(%s)이 없습니다. `cd engine && ../.venv/bin/python scripts/build_panel_from_nemotron.py`를 실행해 패널을 만들어 주세요.", panel.BUNDLE)
            if not settings.web_out.is_dir():
                log.warning("웹 화면 빌드 폴더(%s)가 없습니다. `cd web && npm ci && npm run build`를 실행해 화면을 빌드해 주세요.", settings.web_out)
            if settings.jev_provider in ("api", "upstage") and not jev.available():
                key_name = "UPSTAGE_API_KEY" if settings.jev_provider == "upstage" else "TYPESAFE_API_KEY"
                log.warning(".env 설정 또는 %s가 비어 있습니다. `cp .env.example .env && chmod 600 .env` 후 키를 넣거나 mock 프로필로 실행해 주세요.", key_name)
            if settings.demo_login:
                log.warning("PP_DEMO_LOGIN=1: every visitor is served as %s without a code. Local demonstration only.", auth.DEMO_EMAIL)
            runner.start()
        yield
        if start_workers:
            runner.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db, app.state.settings, app.state.runner = db, settings, runner

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail)}
        return JSONResponse({"error": detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse({"error": {"code": "invalid_input", "message": "입력 형식이 올바르지 않습니다."}}, status_code=422)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/") and request.method in ("POST", "PATCH", "PUT", "DELETE"):
            if request.headers.get(CLIENT_HEADER) != "web":
                return JSONResponse({"error": {"code": "bad_client", "message": "허용되지 않은 요청입니다."}}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current_user(request: Request) -> dict:
        user = auth.session_user(db, request.cookies.get(COOKIE))
        if not user and settings.demo_login:
            return auth.demo_user(db)
        if not user:
            raise ApiError(401, "login_required", "로그인이 필요합니다.")
        return user

    def owned_survey(survey_id: str, user: dict):
        row = db.one("SELECT * FROM surveys WHERE id=? AND user_id=?", (survey_id, user["id"]))
        if not row:
            raise ApiError(404, "not_found", "미리보기를 찾을 수 없습니다.")
        return row

    @app.get("/api/config")
    def config():
        try:
            _, version = panel.load()
        except (FileNotFoundError, pp_config.DataMissing):
            raise ApiError(
                503,
                "panel_missing",
                "합성 인물 패널 파일(engine/ppservice/data/panel-20k.jsonl.gz)이 없습니다. "
                "터미널에서 `cd engine && ../.venv/bin/python scripts/build_panel_from_nemotron.py`를 실행해 패널을 만든 뒤 서버를 다시 시작해 주세요.",
            )
        try:
            model_profile = profile.current()
            decision_model = jev.model()
            holdout = profile.holdout()
        except jev.JevError as e:
            raise ApiError(
                503,
                "config_error",
                f"모델 환경변수(.env) 설정에 오류가 있습니다({e}). `.env` 파일의 UPSTAGE_BASE_URL·PP_UPSTAGE_REGION 등을 확인해 주세요.",
            )
        setup_warnings: list[str] = []
        if settings.jev_provider in ("api", "upstage") and not jev.available():
            key_name = "UPSTAGE_API_KEY" if settings.jev_provider == "upstage" else "TYPESAFE_API_KEY"
            env_hint = "`.env` 파일이 없으면 `cp .env.example .env && chmod 600 .env`로 만든 뒤 " if not (REPO_ROOT / ".env").exists() else "`.env` 파일에 "
            setup_warnings.append(f"{env_hint}{key_name}를 설정해 주세요. 키 없이 화면만 시험하려면 `scripts/serve-profile.sh mock`을 사용하세요.")
        return {"service": True, "demo_login": settings.demo_login, "mock": settings.jev_provider == "mock", "n": settings.n,
                "decision_provider": settings.jev_provider, "decision_model": decision_model, "model_profile": model_profile, "holdout": holdout,
                "daily_runs": settings.daily_runs, "retention_days": settings.retention_days,
                "max_policy": settings.max_policy, "max_question": settings.max_question, "max_option": settings.max_option,
                "panel_version": version, "baseline": aggregate.load_baseline(), "accuracy": aggregate.unavailable_accuracy(),
                "future_available": panel.future_available(), "future_year": pp_config.FUTURE_YEAR,
                "setup_warnings": setup_warnings}

    @app.post("/api/login")
    def login(body: LoginBody, request: Request, response: Response):
        ip = request.client.host if request.client else "unknown"
        try:
            result = auth.login(db, body.email, body.code, ip, settings.session_days)
        except PermissionError:
            raise ApiError(429, "throttled", "로그인 시도가 너무 많습니다. 10분 뒤 다시 시도해 주세요.")
        if not result:
            raise ApiError(401, "bad_login", "이메일 또는 접속 코드가 맞지 않습니다.")
        response.set_cookie(COOKIE, result[0], max_age=settings.session_days * 86400, httponly=True,
                            samesite="strict", secure=settings.cookie_secure, path="/")
        return {"ok": True}

    @app.post("/api/logout")
    def logout(request: Request, response: Response):
        auth.logout(db, request.cookies.get(COOKIE))
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return {"email": user["email"]}

    @app.post("/api/lint")
    def check_question(body: LintBody, user: dict = Depends(current_user)):
        return {"findings": lint.check(body.policy_text, body.question, body.options)}

    @app.post("/api/question-design")
    def design_questions(body: DesignBody, user: dict = Depends(current_user)):
        """Elephant drafts candidate questions; each is reviewed by an isolated goldfish call and the rule lint."""
        from .survey import design

        text = body.policy_text.strip()
        if len(text) < 30:
            raise ApiError(422, "invalid_policy", "정책 문안이 너무 짧습니다.")
        try:
            return design.propose(body.title.strip()[:100], text[:settings.max_policy * 4], evaluate=runner.evaluate,
                                  pilot_n=settings.design_pilot_n)
        except llm.LLMError as e:
            log.warning("question design failed: %s", e)
            raise ApiError(502, "design_unavailable", "문항 후보를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.")

    @app.get("/api/lawmaking")
    def search_notices(q: str = "", page: int = 1, user: dict = Depends(current_user)):
        """Title search; an empty query lists the notices currently open for comment."""
        q = q.strip()
        if q and not 2 <= len(q) <= 50:
            raise ApiError(422, "invalid_query", "검색어를 2자 이상 넣어 주세요.")
        try:
            page = max(1, min(page, 50))
            return lawmaking.search(q, page) if q else lawmaking.recent(page=page)
        except lawmaking.LawmakingError as e:
            raise ApiError(502, "lawmaking_" + e.code, e.message)

    @app.get("/api/lawmaking/{seq}")
    def get_notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "", user: dict = Depends(current_user)):
        try:
            found = lawmaking.notice(seq, mapping_lbic_id, announce_type)
        except lawmaking.LawmakingError as e:
            status = 404 if e.code == "not_found" else 422 if e.code == "invalid_metadata" else 502
            raise ApiError(status, "lawmaking_" + e.code, e.message)
        text = lawmaking.clip(found["text"], settings.max_policy)
        return {**found, "text": text, "full_length": len(found["text"]), "clipped": len(text) < len(found["text"])}

    @app.get("/api/surveys")
    def list_surveys(user: dict = Depends(current_user)):
        rows = db.all("SELECT s.*, (SELECT status FROM runs r WHERE r.survey_id=s.id ORDER BY created_at DESC LIMIT 1) AS last_status,"
                      " (SELECT COUNT(*) FROM runs r WHERE r.survey_id=s.id) AS n_runs"
                      " FROM surveys s WHERE s.user_id=? ORDER BY s.updated_at DESC", (user["id"],))
        return {"surveys": [{"id": r["id"], "title": r["title"], "updated_at": r["updated_at"], "n_runs": r["n_runs"],
                             "last_status": r["last_status"], "headline": _headline(r["id"])} for r in rows]}

    def _headline(survey_id: str) -> dict | None:
        """The latest finished run's top option, its share and stability, for the list view."""
        row = db.one("SELECT result FROM runs WHERE survey_id=? AND status='succeeded' ORDER BY created_at DESC LIMIT 1",
                     (survey_id,))
        if not row or not row["result"]:
            return None
        res = json.loads(row["result"])
        try:
            return {"option": res["options"][res["top"]], "percent": res["percent"][res["top"]],
                    "unstable": bool(res.get("unstable"))}
        except (KeyError, IndexError, TypeError):
            return None

    @app.post("/api/surveys", status_code=201)
    def create_survey(body: SurveyBody, user: dict = Depends(current_user)):
        title, text = body.title.strip(), body.policy_text.strip()
        problems = []
        if not title:
            problems.append("정책 이름을 입력해 주세요.")
        if len(title) > 100:
            problems.append("정책 이름은 100자 이내로 써 주세요.")
        if len(text) < 30:
            problems.append("정책 설명을 30자 이상 써 주세요. 응답자가 읽을 내용입니다.")
        if len(text) > settings.max_policy:
            problems.append(f"정책 설명은 {settings.max_policy:,}자 이내로 줄여 주세요({len(text):,}자).")
        if lint.RRN.search(text) or lint.PHONE.search(text):
            problems.append("주민등록번호·휴대전화 번호로 보이는 내용이 있습니다. 지우고 다시 입력해 주세요.")
        if problems:
            raise ApiError(422, "invalid_survey", " ".join(problems))
        survey_id = "s_" + secrets.token_hex(8)
        with db.tx() as con:
            con.execute("INSERT INTO surveys(id, user_id, title, policy_text, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (survey_id, user["id"], title, text, now(), now()))
        return {"id": survey_id}

    @app.get("/api/surveys/{survey_id}")
    def get_survey(survey_id: str, user: dict = Depends(current_user)):
        s = owned_survey(survey_id, user)
        runs = db.all("SELECT * FROM runs WHERE survey_id=? ORDER BY created_at DESC, rowid DESC", (survey_id,))
        return {"id": s["id"], "title": s["title"], "policy_text": s["policy_text"], "created_at": s["created_at"],
                "runs": [jobs.run_view(r) for r in runs]}

    @app.delete("/api/surveys/{survey_id}")
    def delete_survey(survey_id: str, user: dict = Depends(current_user)):
        owned_survey(survey_id, user)
        run_ids = [r["id"] for r in db.all("SELECT id FROM runs WHERE survey_id=?", (survey_id,))]
        with db.tx() as con:
            con.execute("DELETE FROM surveys WHERE id=? AND user_id=?", (survey_id, user["id"]))
        deep.remove_work(settings, run_ids)  # the working folders hold the policy text
        db.checkpoint()
        return {"ok": True}

    @app.post("/api/surveys/{survey_id}/runs", status_code=202)
    def start_run(survey_id: str, body: QuestionBody, user: dict = Depends(current_user)):
        try:
            run, created = jobs.submit(db, settings, user["id"], survey_id, body.question, body.options, future=body.future)
        except jobs.IntakeError as e:
            raise ApiError(e.status, e.code, e.message, e.findings)
        runner.wake.set()
        return {"run": run, "created": created}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, user: dict = Depends(current_user)):
        row = db.one("SELECT * FROM runs WHERE id=? AND user_id=?", (run_id, user["id"]))
        if not row:
            raise ApiError(404, "not_found", "실행 기록을 찾을 수 없습니다.")
        return {"run": jobs.run_view(row)}

    @app.post("/api/runs/{run_id}/retry", status_code=202)
    def retry_run(run_id: str, user: dict = Depends(current_user)):
        try:
            run = jobs.retry(db, settings, user["id"], run_id)
        except jobs.IntakeError as e:
            raise ApiError(e.status, e.code, e.message, e.findings)
        runner.wake.set()
        return {"run": run}

    @app.post("/api/runs/{run_id}/rule")
    def rule_view(run_id: str, body: RuleBody, user: dict = Depends(current_user)):
        try:
            return {"rule_view": jobs.rule_view_for_run(db, user["id"], run_id, body.model_dump())}
        except jobs.IntakeError as e:
            raise ApiError(e.status, e.code, e.message, e.findings)

    @app.get("/api/runs/{run_id}/visit")
    def visit_view(run_id: str, user: dict = Depends(current_user)):
        try:
            return {"visit": jobs.visit_view_for_run(db, user["id"], run_id)}
        except jobs.IntakeError as e:
            raise ApiError(e.status, e.code, e.message, e.findings)

    @app.get("/api/runs/{run_id}/deep")
    def get_deep(run_id: str, user: dict = Depends(current_user)):
        try:
            return {"deep": deep.get(db, user["id"], run_id)}
        except deep.DeepError as e:
            raise ApiError(e.status, e.code, e.message)

    @app.post("/api/runs/{run_id}/deep", status_code=202)
    def start_deep(run_id: str, user: dict = Depends(current_user)):
        try:
            view, created = deep.request(db, settings, user["id"], run_id)
        except deep.DeepError as e:
            raise ApiError(e.status, e.code, e.message)
        runner.deep_wake.set()
        return {"deep": view, "created": created}

    @app.get("/api/runs/{run_id}/deep/bundle")
    def get_deep_bundle(run_id: str, user: dict = Depends(current_user)):
        try:
            return {"bundle": deep.bundle(db, user["id"], run_id)}
        except deep.DeepError as e:
            raise ApiError(e.status, e.code, e.message)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
    def api_not_found(rest: str):
        raise ApiError(404, "not_found", "없는 주소입니다.")

    if settings.web_out.is_dir():
        app.mount("/", StaticFiles(directory=settings.web_out, html=True), name="web")
    else:
        @app.get("/{rest:path}", response_class=HTMLResponse)
        def web_not_built(rest: str):
            body = (
                "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
                "<title>웹 화면 빌드 필요 · 백번 미리 묻다</title></head>"
                "<body style='font-family:sans-serif;max-width:680px;margin:40px auto;line-height:1.6;padding:0 16px'>"
                "<h1>웹 화면 빌드(web/out)가 준비되지 않았습니다</h1>"
                "<p>API 서버는 실행 중이지만 정적 웹 화면 폴더(<code>web/out</code>)가 없어 페이지를 열 수 없습니다.</p>"
                "<p>터미널에서 아래 명령으로 화면을 빌드한 뒤 서버를 다시 시작해 주세요.</p>"
                "<pre style='background:#f4f5f6;padding:12px;border-radius:6px'>cd web &amp;&amp; npm ci &amp;&amp; npm run build</pre>"
                "</body></html>"
            )
            return HTMLResponse(body, status_code=503)
    return app
