"""Per-run limits shared by every role and worker, including unsuccessful attempts."""
from __future__ import annotations

import contextvars
import json
import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor as _Executor
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path


class BudgetExceeded(RuntimeError):
    """Terminal: never retry this exception as a model failure."""


@dataclass(frozen=True)
class Limits:
    max_calls: int = 100_000
    max_output_tokens: int = 16_384
    max_retries: int = 2
    max_concurrency: int = 8
    max_cost_usd: float | None = 10.0

    def __post_init__(self):
        for name in ("max_calls", "max_output_tokens", "max_concurrency"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if isinstance(self.max_retries, bool) or not isinstance(self.max_retries, int) or self.max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        if self.max_cost_usd is not None and (not math.isfinite(self.max_cost_usd) or self.max_cost_usd < 0):
            raise ValueError("max_cost_usd must be finite and nonnegative")


_current = contextvars.ContextVar("pp_budget", default=None)
_prices = contextvars.ContextVar("pp_prices", default=None)
_receipt = contextvars.ContextVar("pp_budget_receipt", default=None)


def current():
    return _current.get()


class ThreadPoolExecutor(_Executor):
    """Preserve this run's budget in nested worker threads; separate runs stay separate."""
    def submit(self, fn, /, *args, **kwargs):
        return super().submit(contextvars.copy_context().run, fn, *args, **kwargs)


def record_usage(usage):
    receipt = _receipt.get()
    if receipt is not None:
        receipt["usage"] = usage
    ledger = current()
    tokens = (usage or {}).get("output_tokens", (usage or {}).get("completion_tokens"))
    if ledger is not None and tokens is not None and int(tokens) > ledger.limits.max_output_tokens:
        ledger.stopped = True
        raise BudgetExceeded("provider exceeded the requested output token limit")


def output_limit(default=16_384):
    return min(default, current().limits.max_output_tokens) if current() else default


def retries_limit(requested):
    return min(requested, current().limits.max_retries) if current() else requested


def check_output(raw):
    """Fail closed on a provider ignoring the requested cap (including CLI/typed APIs)."""
    ledger = current()
    if ledger is not None and len(raw.encode("utf-8")) > ledger.limits.max_output_tokens * 4:
        ledger.stopped = True
        raise BudgetExceeded("model output exceeded the run output length limit")


@contextmanager
def use_prices(rates):
    token = _prices.set(rates)
    try:
        yield
    finally:
        _prices.reset(token)


def prices(role, mock=False):
    if mock:
        return (0.0, 0.0)
    if _prices.get() is not None:
        return _prices.get()[role]
    if role == "jev":
        from . import jev
        if not jev.custom_endpoint():
            return (jev.price_per_m_input(), 0.0)
    prefix = "PP_JEV" if role == "jev" else "PP_LLM"
    values = tuple(os.environ.get(prefix + suffix) for suffix in ("_INPUT_USD_PER_M", "_OUTPUT_USD_PER_M"))
    if any(v is None for v in values):
        return None
    result = tuple(float(v) for v in values)
    if any(not math.isfinite(v) or v < 0 for v in result):
        raise ValueError("model prices must be finite and nonnegative")
    return result


class Budget:
    def __init__(self, limits=None, path: Path | None = None):
        self.limits = limits or Limits()
        self.path = path
        self.lock = threading.RLock()
        self.slots = threading.BoundedSemaphore(self.limits.max_concurrency)
        self.journal = path.with_suffix(".attempts.jsonl") if path else None
        self._reload()
        self.stopped = False

    def _reload(self):
        path = self.path
        self.entries = []
        if self.journal and self.journal.exists():
            for line in self.journal.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    # A torn final write is not a license to call again.
                    raise BudgetExceeded("budget journal is incomplete; manual accounting is required")
                index = event["index"]
                if index == len(self.entries):
                    self.entries.append(event["entry"])
                else:
                    self.entries[index] = event["entry"]
        elif path and path.exists():
            saved = json.loads(path.read_text())
            if saved.get("calls", 0) and "attempts" not in saved:
                raise BudgetExceeded("budget attempt journal is missing; manual accounting is required")
            self.entries = saved.get("attempts", [])
        self.spent = sum(e.get("cost_usd", e["reserved_usd"]) or 0 for e in self.entries)
        self.unknown = sum(e.get("status") != "known" for e in self.entries)
        self.unpriced = sum(e.get("reserved_usd") is None for e in self.entries)

    def snapshot(self):
        with self.lock:
            return {"limits": asdict(self.limits), "calls": len(self.entries),
                    "cost_usd": None if self.unpriced else self.spent,
                    "reserved_cost_usd": None if self.unpriced else self.spent,
                    "cost_status": "unknown" if self.unknown else "known",
                    "attempts": [dict(e) for e in self.entries]}

    def _save(self, index):
        if self.path:
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"index": index, "entry": self.entries[index]}, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            temp = self.path.with_suffix(".tmp")
            summary = {"limits": asdict(self.limits), "calls": len(self.entries),
                       "cost_usd": None if self.unpriced else self.spent,
                       "cost_status": "unknown" if self.unknown else "known", "journal": self.journal.name}
            temp.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            temp.replace(self.path)

    @contextmanager
    def scope(self):
        from .filelock_util import lock_file, unlock_file
        handle = self.path.with_suffix(".lock").open("a+") if self.path else None
        try:
            if handle:
                try:
                    lock_file(handle, nonblocking=True)
                except OSError as e:
                    raise BudgetExceeded("another process is already using this run budget") from e
                self._reload()
            token = _current.set(self)
            try:
                yield self
            finally:
                _current.reset(token)
        finally:
            if handle:
                unlock_file(handle)
                handle.close()

    @contextmanager
    def attempt(self, role, payload, *, mock=False, cli=False):
        with self.slots:
            rate = None if cli else prices("jev" if role.startswith("jev:") else "llm", mock)
            # A byte upper bound avoids underestimating multilingual text tokenization.
            tokens = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024
            reserved = ((tokens * rate[0] + self.limits.max_output_tokens * rate[1]) / 1e6) if rate else None
            with self.lock:
                spent = self.spent
                cap = self.limits.max_cost_usd
                if (self.stopped or len(self.entries) >= self.limits.max_calls or
                    (cap is not None and (reserved is None or cli or spent + reserved > cap))):
                    self.stopped = True
                    raise BudgetExceeded("run limit reached or monetary cost cannot be bounded; use a new run or explicit limits")
                entry = {"role": role, "reserved_usd": reserved, "status": "unknown"}
                self.entries.append(entry)
                index = len(self.entries) - 1
                self.spent += reserved or 0
                self.unknown += 1
                self.unpriced += reserved is None
                self._save(index)  # keep the reservation even after process death or timeout
            receipt = {}
            token = _receipt.set(receipt)
            try:
                yield
            finally:
                _receipt.reset(token)
                with self.lock:
                    usage = receipt.get("usage")
                    if mock:
                        usage = {"input_tokens": 0, "output_tokens": 0}
                    if rate and usage is not None:
                        inp = usage.get("input_tokens", usage.get("prompt_tokens"))
                        out = usage.get("output_tokens", usage.get("completion_tokens"))
                        if inp is not None and (out is not None or rate[1] == 0):
                            cost = (max(0, int(inp)) * rate[0] + max(0, int(out or 0)) * rate[1]) / 1e6
                            self.unknown -= 1
                            entry.update(status="known", cost_usd=cost, usage=usage)
                            self.spent = math.fsum(e.get("cost_usd", e["reserved_usd"]) or 0 for e in self.entries)
                            if self.limits.max_cost_usd is not None and self.spent >= self.limits.max_cost_usd and cost:
                                self.stopped = True
                    self._save(index)


@contextmanager
def attempt(role, payload, **kwargs):
    if current():
        with current().attempt(role, payload, **kwargs):
            yield
    else:
        yield
