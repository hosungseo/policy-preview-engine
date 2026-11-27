"""Per-persona reactions: one independent call each, validated, resumable, quote-checked."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config, llm, prompts, segment

_IMPACT_ALIASES = {"직접적": "직접", "간접적": "간접", "없음": "무관", "해당없음": "무관", "관계없음": "무관"}
_TRUE = {"true", "예", "네", "yes", "1"}


def _keywords(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()][:3]


def normalize_reaction(d: dict) -> dict:
    try:
        support = int(round(float(d["support"])))
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError(f"bad support: {d.get('support')!r}") from e
    if not -2 <= support <= 2:
        raise ValueError(f"support out of range: {support}")
    impact = str(d.get("impact", "")).strip()
    impact = _IMPACT_ALIASES.get(impact, impact)
    if impact not in config.IMPACTS:
        raise ValueError(f"bad impact: {impact!r}")
    reason = str(d.get("reason", "")).strip()
    if len(reason) < 5:
        raise ValueError("reason too short")
    would = d.get("would_comment")
    if isinstance(would, str):
        would = would.strip().lower() in _TRUE
    return {
        "support": support,
        "impact": impact,
        "trigger_quote": str(d.get("trigger_quote") or "").strip()[:80],
        "reason": reason[:400],
        "concerns": _keywords(d.get("concerns")),
        "hopes": _keywords(d.get("hopes")),
        "suggestion": str(d.get("suggestion") or "").strip()[:200],
        "would_comment": bool(would),
        "channel": str(d.get("channel") or "").strip()[:40],
    }


def verify_quotes(reactions: list[dict], policy_text: str, segments: list[dict]) -> int:
    """Mark each reaction's trigger quote as verified (verbatim in the policy) or not."""
    mismatches = 0
    for r in reactions:
        loc = segment.locate(r.get("trigger_quote", ""), policy_text)
        if loc is None:
            r["quote_verified"] = False
            r["segment_id"] = None
            r["quote_span"] = None
            mismatches += 1
        else:
            r["quote_verified"] = True
            r["segment_id"] = segment.segment_of(loc[0], segments)
            r["quote_span"] = [loc[0], loc[1]]
    return mismatches


def run_reactions(people: list[dict], policy_text: str, out_path: Path, *,
                  workers: int = 8, model: str | None = None) -> tuple[list[dict], list[dict]]:
    """One reaction per person, appended to out_path (JSONL) as it completes; resumes."""
    model = model or config.REACT_MODEL
    done: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["uuid"]] = row
    todo = [p for p in people if p["uuid"] not in done]
    lock = threading.Lock()
    failures: list[dict] = []

    def one(person: dict) -> dict:
        data = llm.complete_json("react", prompts.REACT_SYSTEM, prompts.react_prompt(person, policy_text),
                                 model=model, validate=normalize_reaction)
        return {"uuid": person["uuid"], **data}

    with ThreadPoolExecutor(max_workers=workers) as pool, open(out_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(one, p): p for p in todo}
        for future in as_completed(futures):
            person = futures[future]
            try:
                row = future.result()
            except llm.LLMError as e:
                failures.append({"uuid": person["uuid"], "error": str(e)[:300]})
                continue
            with lock:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[row["uuid"]] = row
    return [done[p["uuid"]] for p in people if p["uuid"] in done], failures
