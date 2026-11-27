"""LLM calls via lean headless Claude Code (`claude -p`), any OpenAI-compatible chat API, or a deterministic mock.

PP_LLM_PROVIDER picks the path: "cli" (default), "openai", "exaone" or "mock". The "openai" path needs
PP_LLM_BASE_URL (for example https://host/v1) and PP_LLM_MODEL, plus PP_LLM_API_KEY when the server asks for one.
PP_LLM_MODEL_REACT and PP_LLM_MODEL_SYNTH may name different models for the per-person answers and for the synthesis
steps.

The "exaone" path is fixed to the EXAONE noncommercial API. Its terms prohibit exposing it as a third-party service,
so each call requires PP_EXAONE_LOCAL_ONLY=1. The launcher must additionally keep the service loopback-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from typing import Callable

from . import budget, config, net

# Measured 2026-09-24: with thinking on, one persona reaction spent ~10.6k thinking tokens and
# 79 s; with thinking off it took ~6 s and ~350 output tokens with the same JSON quality.
LEAN_FLAGS = [
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
    "--tools", "",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--setting-sources", "project",
    "--settings", '{"alwaysThinkingEnabled": false}',
]
CLI_ENV = {"MAX_THINKING_TOKENS": "0"}
MOCK: dict[str, Callable[[str, str], dict]] = {}


class LLMError(RuntimeError):
    pass


def _env(name: str, default: str = "") -> str:
    value = (os.environ.get(name) or "").strip()
    return value or default


def provider() -> str:
    return _env("PP_LLM_PROVIDER", "cli").lower()


def mock_handler(task: str):
    def register(fn):
        MOCK[task] = fn
        return fn
    return register


def seed_of(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


def extract_json(text: str) -> dict:
    s = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", s, re.DOTALL)
    if fenced:
        s = fenced.group(1)
    else:
        found = re.search(r"\{.*\}", s, re.DOTALL)
        if not found:
            raise LLMError(f"no JSON object in output: {s[:120]!r}")
        s = found.group(0)
    try:
        data = json.loads(s)
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON ({e}): {s[:120]!r}") from e
    if not isinstance(data, dict):
        raise LLMError("JSON root is not an object")
    return data


def _cli(system: str, prompt: str, model: str, timeout: int) -> str:
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--system-prompt", system, *LEAN_FLAGS]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
                          cwd=config.llm_cwd(), env={**os.environ, **CLI_ENV})
    if proc.returncode != 0:
        raise LLMError(f"claude -p rc={proc.returncode}: {proc.stderr[:300]}")
    envelope = json.loads(proc.stdout)
    budget.record_usage(envelope.get("usage"))
    if envelope.get("is_error"):
        raise LLMError(f"claude -p error: {str(envelope.get('result'))[:300]}")
    return str(envelope.get("result", ""))


def http_model(model: str) -> str:
    """The model name sent to the OpenAI-compatible server for a pipeline model slot (react or synth)."""
    slot = "REACT" if model == config.REACT_MODEL else "SYNTH"
    name = _env(f"PP_LLM_MODEL_{slot}") or _env("PP_LLM_MODEL")
    if not name:
        raise LLMError("PP_LLM_MODEL is not set")
    return name


def _exaone_max_tokens() -> int:
    """Return a bounded EXAONE output limit; do not let environment configuration create unbounded requests."""
    raw = _env("PP_EXAONE_MAX_TOKENS", "16384")
    try:
        value = int(raw)
    except ValueError as e:
        raise LLMError("PP_EXAONE_MAX_TOKENS must be an integer between 1 and 16384") from e
    if not 1 <= value <= 16384:
        raise LLMError("PP_EXAONE_MAX_TOKENS must be between 1 and 16384")
    return value


def _exaone(system: str, prompt: str, timeout: int) -> str:
    """Call the fixed EXAONE endpoint for local-only, noncommercial use.

    Measured 2026-11-10: the model reasons before answering and the reasoning counts against max_tokens (3.6k tokens
    for the target prompt, over 4k for clustering), so a 2k-4k limit returned empty content. The default limit is
    therefore 16k. PP_EXAONE_THINKING=0 sends `chat_template_kwargs.enable_thinking=false`, which removes the reasoning
    but on long prompts the model then writes its planning into the answer and the JSON can be cut off.
    """
    if _env("PP_EXAONE_LOCAL_ONLY") != "1":
        raise LLMError("EXAONE calls require PP_EXAONE_LOCAL_ONLY=1; do not expose this provider as a third-party service")
    key = _env("EXAONE_API_KEY")
    if not key:
        raise LLMError("EXAONE_API_KEY is not set")
    body = {
        "model": "k-exaone_v2.5",
        "temperature": float(_env("PP_LLM_TEMPERATURE", "0.7")),
        "max_tokens": budget.output_limit(_exaone_max_tokens()),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    if _env("PP_EXAONE_THINKING") == "0":
        body["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {"Content-Type": "application/json", "User-Agent": "policy-preview/0.1", "Authorization": f"Bearer {key}"}
    try:
        out = json.loads(net.post("https://api.exaone.ai/v1/chat/completions",
                                  json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, timeout=timeout))
    except net.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.body!r}") from e
    except (net.NetError, json.JSONDecodeError) as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e
    budget.record_usage(out.get("usage"))
    try:
        return str(out["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected response shape: {str(out)[:200]}") from e


def _http(system: str, prompt: str, model: str, timeout: int) -> str:
    base = _env("PP_LLM_BASE_URL").rstrip("/")
    if not base:
        raise LLMError("PP_LLM_BASE_URL is not set")
    body = {"max_tokens": budget.output_limit(), "model": http_model(model), "temperature": float(_env("PP_LLM_TEMPERATURE", "0.7")),
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
    headers = {"Content-Type": "application/json", "User-Agent": "policy-preview/0.1"}
    key = _env("PP_LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        out = json.loads(net.post(f"{base}/chat/completions", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                  headers=headers, timeout=timeout))
    except net.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {e.body!r}") from e
    except (net.NetError, json.JSONDecodeError) as e:
        raise LLMError(f"{type(e).__name__}: {e}") from e
    budget.record_usage(out.get("usage"))
    try:
        text = out["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected response shape: {str(out)[:200]}") from e
    # Reasoning models may put their thinking in the content; keep what follows it.
    return re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL)


def _call(task: str, system: str, prompt: str, model: str, timeout: int) -> str:
    kind = provider()
    if kind == "mock":
        return _mock(task, system, prompt)
    if kind == "openai":
        return _http(system, prompt, model, timeout)
    if kind == "exaone":
        return _exaone(system, prompt, timeout)
    return _cli(system, prompt, model, timeout)


def model_label(model: str) -> str:
    """The model actually used for a slot, for the run's record."""
    if provider() == "openai":
        return http_model(model)
    if provider() == "exaone":
        return "k-exaone_v2.5"
    return model


def _mock(task: str, system: str, prompt: str) -> str:
    from . import mock  # noqa: F401  (registers handlers)

    if task not in MOCK:
        raise LLMError(f"no mock handler for task {task!r}")
    return json.dumps(MOCK[task](system, prompt), ensure_ascii=False)


def complete_json(task: str, system: str, prompt: str, *, model: str,
                  validate: Callable[[dict], dict] | None = None,
                  retries: int = 2, timeout: int = 300) -> dict:
    """Call the model, parse one JSON object, validate it; retry on any failure."""
    last: Exception | None = None
    retries = budget.retries_limit(retries)
    for attempt in range(retries + 1):
        try:
            with budget.attempt(f"llm:{task}", [system, prompt], mock=provider() == "mock", cli=provider() == "cli"):
                raw = _call(task, system, prompt, model, timeout)
            budget.check_output(raw)
            data = extract_json(raw)
            return validate(data) if validate else data
        except (LLMError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
            last = e
            if provider() != "mock":
                time.sleep(3 * (attempt + 1))
    raise LLMError(f"{task}: failed after {retries + 1} attempts: {last}")
