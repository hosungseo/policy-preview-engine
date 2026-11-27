"""Ask every panel member the question three ways (main, placebo, options reversed), one Jev call each."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

log = logging.getLogger("ppservice.survey")

INSTRUCTIONS = ("Answer the survey question in `question` as this person would, after reading the policy in "
                "`policy`. Pick the option they would most likely choose.")
# Content-free control sentence: how much appending any text moves answers on its own.
PLACEBO = "※ 설명은 여기까지입니다."
ARMS = ("main", "placebo", "reversed")
# Optional pair asked when the run turns on "5년 뒤 보기": the same survivors with a base-year state block and with their
# projected 2030 state block (ppservice/survey/panel.future_pair). Both carry the block so only the states differ.
FUTURE_ARMS = ("future_base", "future")
ATTEMPTS = 3
MAX_CONSECUTIVE_FAILURES = 40
MAX_FAILURE_RATE = 0.05
BATCH = 500


class RunFailed(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail[:300]


class Cancelled(Exception):
    pass


def option_keys(options: list[str]) -> list[str]:
    return [f"o{i + 1}" for i in range(len(options))]


# "Don't know"-type options stay last when the order is reversed, as in survey practice. Reversing them too put
# "잘 모르겠다" first and moved every model toward the first substantive option (2026-11-10 holdout experiment:
# Jev's order shift on a 3-option item fell from 7.9 to 0.2 points once it stayed last).
UNDECIDED = ("모르", "모름", "의견 없", "무응답")


def is_undecided(option: str) -> bool:
    return any(token in option.replace(" ", "") for token in (t.replace(" ", "") for t in UNDECIDED))


def jev_questions(options: list[str], reverse: bool = False) -> dict:
    """Keys stay o1..oN in every arm; only their order in the request is reversed for the stability arm.
    Undecided options keep their place at the end."""
    pairs = list(zip(option_keys(options), options))
    if reverse:
        pairs = [p for p in pairs if not is_undecided(p[1])][::-1] + [p for p in pairs if is_undecided(p[1])]
    return {"q": {"type": "choice", "criteria": dict(pairs), "instructions": INSTRUCTIONS}}


def state_for(arm: str, spec: dict, person: dict) -> dict:
    text = spec["policy_text"].strip()
    if arm == "placebo":
        text += "\n" + PLACEBO
    return {"policy": {"title": spec["title"], "text": text}, "question": spec["question"], "person": person["profile"]}


def normalize(probs: dict, keys: list[str]) -> list[float]:
    values = [max(0.0, float(probs.get(k, 0.0))) for k in keys]
    total = sum(values)
    if total <= 0:
        raise ValueError("no probability mass")
    return [round(v / total, 6) for v in values]


def estimate_tokens(spec: dict, profile_chars: int) -> int:
    """Per-call input tokens; calibrated on a measured call (895 tokens for a ~1.1k-character request)."""
    chars = profile_chars + len(spec["policy_text"]) + len(spec["question"]) + sum(len(o) for o in spec["options"])
    return int(chars / 1.3) + 250


def execute(runner, spec: dict, people: list[dict], evaluate: Callable, threads: int,
            extra: dict[str, list[dict]] | None = None) -> dict:
    """Fill runner's answers for every (arm, person) not answered yet. Returns {"failed": n, "model": str}.
    `extra` adds arms with their own people lists (the "5년 뒤 보기" pair: the same people with a base-year and a
    projected profile)."""
    keys = option_keys(spec["options"])
    questions = {False: jev_questions(spec["options"]), True: jev_questions(spec["options"], reverse=True)}
    done = runner.done_keys()
    arms = {**{arm: people for arm in ARMS}, **(extra or {})}
    tasks = [(arm, p) for arm, members in arms.items() for p in members if (arm, p["uuid"]) not in done]
    state = {"failed": 0, "consecutive": 0, "model": ""}
    lock = threading.Lock()

    def one(task: tuple[str, dict]) -> int:
        arm, person = task
        for attempt in range(ATTEMPTS):
            runner.check_alive()
            try:
                out = evaluate(state_for(arm, spec, person), questions[arm == "reversed"], cache=False, retries=0,
                               timeout=runner.call_timeout())
                probs = normalize(out["answers"]["q"]["probabilities"], keys)
            except (Cancelled, RunFailed):
                raise
            except Exception as e:  # network, HTTP 429/5xx, malformed answer
                with lock:
                    state["consecutive"] += 1
                    too_many = state["consecutive"] >= MAX_CONSECUTIVE_FAILURES
                if too_many:
                    raise RunFailed("model_unavailable", f"{type(e).__name__}: {e}") from e
                runner.sleep(2 * (attempt + 1))
                continue
            tokens = int((out.get("usage") or {}).get("input_tokens") or 0)
            runner.save_answer(arm, person["uuid"], probs, tokens)
            with lock:
                state["consecutive"] = 0
                state["model"] = out.get("model") or state["model"]
            return tokens
        with lock:
            state["failed"] += 1
        return 0

    est = estimate_tokens(spec, max((len(p["profile"]) for members in arms.values() for p in members), default=0))
    with ThreadPoolExecutor(max_workers=threads) as pool:
        for start in range(0, len(tasks), BATCH):
            chunk = tasks[start:start + BATCH]
            reservation = runner.reserve(len(chunk), est)
            futures = [pool.submit(one, t) for t in chunk]
            used, error = 0, None
            for f in futures:
                try:
                    used += f.result()
                except (Cancelled, RunFailed) as e:
                    error = error or e
            runner.settle(reservation, used)
            if error:
                for f in futures:
                    f.cancel()
                raise error
            runner.progress()
    total = sum(len(members) for members in arms.values())
    if state["failed"] / max(1, total) > MAX_FAILURE_RATE:
        raise RunFailed("too_many_failures", f"{state['failed']} of {total} calls failed")
    return {"failed": state["failed"], "model": state["model"]}
