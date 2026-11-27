"""Service settings, all read from the environment with pilot defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
def _env(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def jev_price_per_m_input() -> float:
    """Input-token price for the currently selected decision-model provider (and Upstage model)."""
    if _env("PP_JEV_PROVIDER", "api").lower() == "upstage":
        from pp import jev
        return jev.upstage_price_per_m_input(_env("PP_JEV_MODEL", "solar-decide"))
    return 0.042


def _int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _path(name: str, default: str) -> Path:
    """Relative paths are taken from the repository root, not the working directory."""
    path = Path(_env(name, default)).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    web_out: Path
    jev_provider: str      # api | upstage | mock
    n: int                 # synthetic respondents per run (each asked three times: main, placebo, reversed)
    threads: int           # concurrent Jev calls inside one run
    workers: int           # runs executed at the same time
    daily_runs: int        # per user, retries included
    daily_budget_usd: float
    run_timeout: int
    retention_days: int
    max_policy: int
    max_question: int
    max_option: int
    cookie_secure: bool
    session_days: int
    # 심층 분석 (ppservice.deep): the pipeline sizes for one deep analysis of a finished run
    deep_rep: int = 300       # respondents heard one by one, drawn from the survey's own sample
    deep_aff: int = 100       # people the policy touches directly, searched in the whole 20k panel
    deep_jev: int = 2000      # respondents asked the closed checks
    deep_alt: int = 500       # respondents in the paired amendment test
    deep_workers: int = 8     # concurrent language-model calls
    deep_timeout: int = 5400
    daily_deeps: int = 3      # per user
    # 문항 설계 (ppservice.survey.design): synthetic respondents in the quick pilot of each candidate question
    design_pilot_n: int = 40
    # 시연 모드: a request without a session is served as one shared demo account, so a reviewer who runs the
    # container locally needs no access code. Never turn this on for a server other people can reach.
    demo_login: bool = False
    max_calls: int = 100_000
    max_output_tokens: int = 16_384
    max_retries: int = 2
    max_concurrency: int = 8
    max_cost_usd: float = 10.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "survey.db"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "ppservice.lock"


def load() -> Settings:
    data_dir = _path("PP_SERVICE_DATA", "service-data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        web_out=_path("PP_WEB_OUT", "web/out"),
        jev_provider=_env("PP_JEV_PROVIDER", "api").lower(),
        n=_int("PP_SURVEY_N", 3000),
        threads=_int("PP_SURVEY_THREADS", 16),
        workers=_int("PP_WORKERS", 1),
        daily_runs=_int("PP_DAILY_RUNS", 5),
        daily_budget_usd=_float("PP_DAILY_BUDGET_USD", 10.0),
        run_timeout=_int("PP_RUN_TIMEOUT", 1800),
        retention_days=_int("PP_RETENTION_DAYS", 30),
        max_policy=_int("PP_MAX_POLICY", 1500),
        max_question=_int("PP_MAX_QUESTION", 200),
        max_option=_int("PP_MAX_OPTION", 40),
        cookie_secure=_env("PP_COOKIE_SECURE", "0") == "1",
        session_days=_int("PP_SESSION_DAYS", 14),
        deep_rep=_int("PP_DEEP_REP", 300),
        deep_aff=_int("PP_DEEP_AFF", 100),
        deep_jev=_int("PP_DEEP_JEV", 2000),
        deep_alt=_int("PP_DEEP_ALT", 500),
        deep_workers=_int("PP_DEEP_WORKERS", 8),
        deep_timeout=_int("PP_DEEP_TIMEOUT", 5400),
        daily_deeps=_int("PP_DAILY_DEEPS", 3),
        design_pilot_n=_int("PP_DESIGN_PILOT_N", 40),
        demo_login=_env("PP_DEMO_LOGIN", "0") == "1",
        max_calls=_int("PP_MAX_CALLS", 100_000),
        max_output_tokens=_int("PP_MAX_OUTPUT_TOKENS", 16_384),
        max_retries=_int("PP_MAX_RETRIES", 2),
        max_concurrency=_int("PP_MAX_CONCURRENCY", 8),
        max_cost_usd=_float("PP_MAX_COST_USD", 10.0),
    )
