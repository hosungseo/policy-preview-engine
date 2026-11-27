"""Typed decision-model client for TypeSafe Jev and Upstage Solar Decide.

The provider is selected with ``PP_JEV_PROVIDER``: ``api`` (TypeSafe, the legacy default),
``upstage`` (Solar Decide; ``PP_JEV_MODEL=solar-decide-flash`` picks the low-latency variant), or ``mock``.
``PP_JEV_URL`` remains a custom endpoint option for legacy ``api`` deployments; TypeSafe credentials are never sent to that endpoint.  The Upstage endpoint is
``UPSTAGE_BASE_URL`` when set, else the base of ``PP_UPSTAGE_REGION`` (``global`` or ``kr``), else global.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import urllib.parse
import threading
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar

from . import budget, config, net

TYPESAFE_API = "https://api.typesafe.ai/v1/systemone"
UPSTAGE_API = "https://api.upstage.ai/v1/systemone"  # the default (global) Solar Decide endpoint
# Upstage API bases by PP_UPSTAGE_REGION. The Korea region is a private beta that needs an access request; its exact
# paths come with the approval, so UPSTAGE_BASE_URL can name the base directly and wins over the region.
UPSTAGE_REGIONS = {"global": "https://api.upstage.ai/v1", "kr": "https://kr.api.upstage.ai/v1"}
API = TYPESAFE_API  # compatibility for callers that imported the legacy endpoint name
PRICE_PER_M_INPUT = 0.042  # legacy TypeSafe USD per million input tokens; output tokens are free
# Upstage System One models (both beta) and their listed USD price per million input tokens; output tokens are free.
# Source: console.upstage.ai/docs/models/solar-decide and /solar-decide-flash, checked 2026-11-27.
# solar-decide-flash is the low-latency variant: same endpoint, request and response, same listed price.
UPSTAGE_DECIDE_MODELS = {"solar-decide": 0.1, "solar-decide-flash": 0.1}
UPSTAGE_PRICE_PER_M_INPUT = UPSTAGE_DECIDE_MODELS["solar-decide"]

_usage_lock = threading.Lock()
_usage: dict[str, dict] = {}

_request_key = ContextVar("pp_jev_key", default=None)


@contextmanager
def use_key(key):
    """Request-local TypeSafe credentials, without environment or disk fallback."""
    token = _request_key.set(key)
    try:
        yield
    finally:
        _request_key.reset(token)


class RateLimiter:
    """Spaces calls evenly across threads so a run stays under the API limit (1,200 requests/min)
    however many workers it uses and however long each call takes."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        if not self.interval:
            return
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next)
            self._next = at + self.interval
        if at > now:
            time.sleep(at - now)


def _env(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def _rps_from_env() -> float:
    return float(_env("PP_JEV_RPS", "18"))


_limiter = RateLimiter(_rps_from_env())

# On-disk answer cache keyed by the exact request body (model, state and questions in their given order,
# so a reordered option list is a different question). Reruns reuse earlier answers for free.
# PP_JEV_CACHE=0 turns it off; the tests do that by default.
_cache_lock = threading.Lock()
_cache_conn: sqlite3.Connection | None = None
_cache_path = None


def cache_enabled() -> bool:
    return _request_key.get() is None and _env("PP_JEV_CACHE", "1") != "0"


def _cache():
    global _cache_conn, _cache_path
    path = config.data_dir() / "jev-cache.sqlite"
    if _cache_conn is None or _cache_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        _cache_conn = sqlite3.connect(path, check_same_thread=False)
        _cache_conn.execute("PRAGMA journal_mode=WAL")
        _cache_conn.execute("CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, body TEXT NOT NULL, created_at TEXT)")
        _cache_path = path
    return _cache_conn


def _cache_get(key: str) -> dict | None:
    with _cache_lock:
        row = _cache().execute("SELECT body FROM answers WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _cache_put(key: str, out: dict) -> None:
    with _cache_lock:
        conn = _cache()
        conn.execute("INSERT OR REPLACE INTO answers VALUES (?, ?, ?)",
                     (key, json.dumps(out, ensure_ascii=False), datetime.now(timezone.utc).isoformat(timespec="seconds")))
        conn.commit()


class JevError(RuntimeError):
    pass


def provider() -> str:
    if _request_key.get() is not None:
        return "api"
    explicit = _env("PP_JEV_PROVIDER")
    if explicit:
        return explicit.lower()
    return "mock" if _env("PP_LLM_PROVIDER").lower() == "mock" else "api"


def model() -> str:
    return _env("PP_JEV_MODEL") or ("solar-decide" if provider() == "upstage" else "jev-latest")


def custom_endpoint() -> bool:
    """A custom endpoint is a legacy TypeSafe-compatible endpoint, never an Upstage override."""
    if _request_key.get() is not None:
        return False
    return provider() == "api" and bool(_env("PP_JEV_URL"))


def is_korean_host(url: str) -> bool:
    """True only when the URL's host explicitly indicates a Korean region endpoint."""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return bool(host) and (host == "kr.api.upstage.ai" or host.startswith("kr.") or host.endswith(".kr"))


def upstage_base_url() -> str:
    """Upstage API base: UPSTAGE_BASE_URL, else the PP_UPSTAGE_REGION base, else global (no trailing slash).

    An unknown region or a base that is not an https URL is an error, never a silent fallback.
    """
    explicit = _env("UPSTAGE_BASE_URL")
    if explicit:
        parsed = urllib.parse.urlparse(explicit)
        if parsed.scheme != "https" or not parsed.netloc:
            raise JevError("UPSTAGE_BASE_URL must be an https:// URL such as https://kr.api.upstage.ai/v1")
        return explicit.rstrip("/")
    raw = _env("PP_UPSTAGE_REGION")
    if not raw:
        return UPSTAGE_REGIONS["global"]
    region = raw.lower()
    if region not in UPSTAGE_REGIONS:
        raise JevError(f"PP_UPSTAGE_REGION={raw!r} is not supported; use one of {sorted(UPSTAGE_REGIONS)} or leave it empty")
    return UPSTAGE_REGIONS[region]


def upstage_is_korean_region() -> bool:
    """True only when the resolved Upstage base URL (UPSTAGE_BASE_URL > PP_UPSTAGE_REGION > global) is confirmed KR."""
    return is_korean_host(upstage_base_url())


def api_url() -> str:
    """Return the provider-owned endpoint, or the opted-in legacy custom endpoint.

    In particular, ``PP_JEV_URL`` cannot redirect an Upstage credential to another host; only the Upstage
    settings (UPSTAGE_BASE_URL, PP_UPSTAGE_REGION) move the Upstage endpoint.
    """
    if provider() == "upstage":
        return upstage_base_url() + "/systemone"
    return _env("PP_JEV_URL") if custom_endpoint() else TYPESAFE_API


def local() -> bool:
    """Backward-compatible name for callers checking the custom endpoint mode."""
    return custom_endpoint()


def parse_dotenv_line(line: str) -> tuple[str, str] | None:
    """Parse one .env line: handles CRLF, leading/trailing spaces, optional `export `, and matching quotes."""
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.startswith("export") and len(s) > 6 and s[6].isspace():
        s = s[6:].lstrip()
    if "=" not in s:
        return None
    key, value = s.split("=", 1)
    key, value = key.strip(), value.strip()
    if not key:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not value:
        return None
    return key, value


def _env_or_repo_key(name: str) -> str | None:
    key = _env(name)
    if key:
        return key
    env = config.REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            parsed = parse_dotenv_line(line)
            if parsed and parsed[0] == name:
                return parsed[1]
    return None


def api_key() -> str | None:
    """Return only the key belonging to the selected hosted provider."""
    if _request_key.get() is not None:
        return _request_key.get() or None
    if provider() == "upstage":
        return _env_or_repo_key("UPSTAGE_API_KEY")
    return _env_or_repo_key("TYPESAFE_API_KEY")


def upstage_price_per_m_input(name: str | None = None) -> float:
    """Listed input price of an Upstage System One model; an unlisted name is costed as Solar Decide."""
    return UPSTAGE_DECIDE_MODELS.get((name if name is not None else model()).strip().lower(), UPSTAGE_PRICE_PER_M_INPUT)


def price_per_m_input() -> float:
    return upstage_price_per_m_input() if provider() == "upstage" else PRICE_PER_M_INPUT


def available() -> bool:
    if provider() == "mock":
        return True
    if provider() == "upstage":
        return bool(api_key())
    if provider() == "api":
        # Custom endpoints deliberately use only their separately configured PP_JEV_API_KEY, if any.
        return custom_endpoint() or bool(api_key())
    return False


def reset_usage() -> None:
    with _usage_lock:
        _usage.clear()


def usage() -> dict[str, dict]:
    """Calls, input tokens and summed call seconds per task label since the last reset."""
    with _usage_lock:
        return {label: dict(u) for label, u in _usage.items()}


def cost_usd(input_tokens: int) -> float:
    return round(input_tokens / 1_000_000 * price_per_m_input(), 4)


def _record(label: str, input_tokens: int, seconds: float, cached: bool = False) -> None:
    with _usage_lock:
        u = _usage.setdefault(label, {"calls": 0, "input_tokens": 0, "seconds": 0.0, "cached": 0})
        if cached:
            u["cached"] += 1
            return
        u["calls"] += 1
        u["input_tokens"] += input_tokens
        u["seconds"] = round(u["seconds"] + seconds, 3)


def _mock_answer(question: dict, seed: int) -> dict:
    kind = question["type"]
    if kind == "noul":
        return {"type": "noul", "noul": round((seed % 100) / 100, 2)}
    if kind == "choice":
        options = list(question["criteria"])
        pick = sorted(options)[seed % len(options)]  # the same pick whatever order the options come in
        rest = round(0.3 / max(1, len(options) - 1), 4)
        return {"type": "choice", "choice": pick, "confidence": 0.6,
                "probabilities": {o: (0.7 if o == pick else rest) for o in options}}
    levels = question["criteria"]
    top = seed % len(levels)
    rest = 0.2 / max(1, len(levels) - 1)
    probs = {str(i): round(0.8 if i == top else rest, 4) for i in range(len(levels))}
    score = sum(int(i) * p for i, p in probs.items())
    return {"type": "score", "score": round(score, 4), "confidence": 0.6,
            "legend": {str(i): level for i, level in enumerate(levels)}, "probabilities": probs}


def _retry_wait(headers: dict, attempt: int) -> float:
    """Seconds to wait after a 429/5xx. Upstage limits requests and tokens per minute and names the reset time
    (epoch seconds), so a long call can outlast a fixed short back-off; wait until that reset instead."""
    if headers.get("retry-after"):
        try:
            return min(float(headers["retry-after"]), 65.0)
        except ValueError:
            pass
    resets = []
    for name in ("x-upstage-ratelimit-reset-tokens", "x-upstage-ratelimit-reset-requests"):
        try:
            resets.append(float(headers[name]) - time.time())
        except (KeyError, ValueError):
            continue
    if resets:
        return min(max(max(resets), 1.0) + 1.0, 65.0)
    return min(2.0 * (attempt + 1), 30.0)


def evaluate(state, questions: dict, *, label: str = "other", cache: bool = True, retries: int = 4,
             timeout: int = 60) -> dict:
    """One System One call: a state plus a map of typed questions -> typed answers.
    Usage (calls, input tokens, seconds, cache hits) is tallied under `label`.
    cache=False always asks the model (used when measuring repeatability)."""
    started = time.time()
    if provider() == "mock":
        base = json.dumps(state, ensure_ascii=False, sort_keys=True)
        answers = {qid: _mock_answer(q, int(hashlib.sha256((base + qid).encode("utf-8")).hexdigest()[:8], 16))
                   for qid, q in questions.items()}
        with budget.attempt(f"jev:{label}", [state, questions], mock=True):
            pass
        _record(label, 0, time.time() - started)
        result = {"model": "mock", "answers": answers, "usage": {"input_tokens": 0, "output_tokens": 0}}
        budget.check_output(json.dumps(result, ensure_ascii=False))
        return result
    is_custom = custom_endpoint()
    key = _env("PP_JEV_API_KEY") or None if is_custom else api_key()
    if not key and not is_custom:
        name = "UPSTAGE_API_KEY" if provider() == "upstage" else "TYPESAFE_API_KEY"
        raise JevError(f"{name} is not set")
    body = json.dumps({"state": state, "model": model(), "questions": questions}, ensure_ascii=False).encode("utf-8")
    use_cache = cache and cache_enabled()
    # The response belongs to a particular service as well as its body.  This prevents an answer
    # cached from TypeSafe (or a custom server) from satisfying an identical Solar Decide request.
    cache_key = hashlib.sha256(api_url().encode("utf-8") + b"\0" + body).hexdigest()
    if use_cache:
        hit = _cache_get(cache_key)
        if hit is not None:
            _record(label, 0, 0.0, cached=True)
            return hit
    last: Exception | None = None
    retries = budget.retries_limit(retries)
    for attempt in range(retries + 1):
        headers = {"Content-Type": "application/json", "User-Agent": "policy-preview/0.1"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        try:
            _limiter.wait()
            with budget.attempt(f"jev:{label}", [state, questions]):
                out = json.loads(net.post(api_url(), body, headers=headers, timeout=timeout))
                budget.record_usage(out.get("usage"))
            budget.check_output(json.dumps(out, ensure_ascii=False))
            missing = set(questions) - set(out.get("answers", {}))
            if missing:
                raise JevError(f"missing answers: {sorted(missing)[:5]}")
            _record(label, int((out.get("usage") or {}).get("input_tokens") or 0), time.time() - started)
            if use_cache:
                _cache_put(cache_key, out)
            return out
        except net.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                time.sleep(_retry_wait(e.headers, attempt))
                continue
            if e.code == 403 and provider() == "upstage" and b"model_opt_in_required" in (e.body or b""):
                # From 2026-12-23 (KST) both Solar Decide models need the organization owner's beta-terms consent.
                raise JevError("HTTP 403 model_opt_in_required: the Upstage organization owner must agree to the "
                               "beta model terms at https://console.upstage.ai/model-access before "
                               f"{model()} can be used") from e
            raise JevError(f"HTTP {e.code}: {e.body!r}") from e
        except (net.NetError, JevError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise JevError(f"failed after {retries + 1} attempts: {last}")
