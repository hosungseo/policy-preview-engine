"""Local HTTP adapter. Run one process; keys are headers or process environment only."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import public_rules, service
from .jobs import Jobs


class PublicJSONResponse(JSONResponse):
    def render(self, content):
        data = content if isinstance(content, dict) else {"data": content}
        return public_rules.dumps(data).encode("utf-8")


class PolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_text: str = Field(min_length=1, max_length=service.MAX_CHARS)
    sample: StrictInt = Field(default=service.DEFAULT_SAMPLE, ge=1, le=service.MAX_SAMPLE)
    i_confirm_public: StrictBool = False
    limits: dict | None = None
    seed: StrictInt = Field(default=42, ge=0, le=2147483647)


def create_app(jobs: Jobs | None = None) -> FastAPI:
    jobs = jobs or Jobs()

    @asynccontextmanager
    async def lifespan(app):
        yield
        jobs.close()

    app = FastAPI(title="정책 미리듣기", lifespan=lifespan, default_response_class=PublicJSONResponse)

    @app.middleware("http")
    async def loopback_only(request, call_next):
        import ipaddress
        host = request.client.host if request.client else ""
        if host != "testclient":
            try:
                local = ipaddress.ip_address(host).is_loopback
            except ValueError:
                local = False
            if not local:
                return PublicJSONResponse(status_code=403, content={"detail": "localhost only"})
        return await call_next(request)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return PublicJSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        return PublicJSONResponse(status_code=500, content={"detail": "처리 실패: 서버 설정과 연결을 확인하세요."})

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Do not echo submitted values (including misplaced keys) in validation errors.
        return PublicJSONResponse(status_code=422, content={"detail": "Invalid request; use policy_text, sample, seed, i_confirm_public, limits only. "
                                                     "API keys belong in headers or environment variables."})

    @app.post("/estimate")
    def estimate(body: PolicyRequest):
        try:
            return service.estimate(body.policy_text, body.sample, i_confirm_public=body.i_confirm_public, limits=body.limits)
        except service.RequestError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/runs", status_code=202)
    def start(body: PolicyRequest, x_anthropic_api_key: str | None = Header(default=None),
              x_typesafe_api_key: str | None = Header(default=None)):
        env = service.Credentials.from_env()
        keys = service.Credentials(env.anthropic if x_anthropic_api_key is None else x_anthropic_api_key,
                                   env.typesafe if x_typesafe_api_key is None else x_typesafe_api_key)
        try:
            return jobs.start(body.policy_text, body.sample, body.seed, keys, body.i_confirm_public, body.limits)
        except service.RequestError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/runs/{run_id}")
    def get(run_id: str):
        try:
            return jobs.get(run_id)
        except KeyError:
            raise HTTPException(404, "Unknown run id; runs are lost on restart") from None

    return app
