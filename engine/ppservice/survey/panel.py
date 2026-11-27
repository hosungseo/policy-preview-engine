"""The portable synthetic panel: 20k people drawn province × age band × sex in population proportion
from NVIDIA Nemotron-Personas-Korea (1M people, CC BY 4.0), with ready-made persona profiles."""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import random
import threading
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "data" / "panel-20k.jsonl.gz"
# Add-on modules: life context drawn from public statistics (engine/scripts/build_life_context.py) on top of the base
# NVIDIA persona. On by default ("auto": the core bundle plus topical modules whose topic the policy/question mentions);
# PP_PANEL_ADDONS can force "all", a comma list such as "finance,welfare", or "off". With add-ons the panel version
# changes, so results are never shown against checks made on the plain panel.
CONTEXT = BUNDLE.parent / "persona-context" / "life-context-v2.jsonl.gz"
# Life histories and the 2025->2030 projection (engine/scripts/build_life_history.py) behind "5년 뒤 보기".
# PP_PANEL_FUTURE=off hides the option; it is also hidden while the files are not built.
HISTORY = BUNDLE.parent / "persona-context" / "life-history-v1.jsonl.gz"
FORECAST = BUNDLE.parent / "persona-context" / "life-forecast-v1.jsonl.gz"
AGE_BANDS = ["19–29세", "30대", "40대", "50대", "60대", "70세 이상"]
log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache: dict[str, object] = {}
CACHE_MAX = 4


def addons_setting(text: str = "") -> tuple[str, ...]:
    """Add-ons for a run whose policy/question text is `text`; () means the base persona only. PP_PANEL_ADDONS unset
    (or "auto") picks them from the text; without a built life-context file the base persona is used."""
    from pp import life_context

    raw = (os.environ.get("PP_PANEL_ADDONS") or "").strip()
    if raw in ("off", "none"):
        return ()
    if raw in ("", "auto", "default"):
        if not CONTEXT.exists():
            log.warning("life context %s not built; using the base persona without add-ons", CONTEXT.name)
            return ()
        return life_context.auto_addons(text)
    return life_context.parse_addons(raw)


def spec_text(spec: dict) -> str:
    return "\n".join([spec.get("policy_text") or "", spec.get("question") or "", *(spec.get("options") or [])])


def load(path: Path | None = None, addons: tuple[str, ...] | list[str] | str | None = None) -> tuple[list[dict], str]:
    """(people, version). The version is a hash of the bundle contents, plus the chosen add-ons and the life-context
    file's hash when add-ons are attached; it is recorded with every run."""
    from pp import life_context

    path = BUNDLE if path is None else path

    chosen = addons_setting() if addons is None else (() if addons in ("", "off", ()) else life_context.parse_addons(addons))
    with _lock:
        key = f"{path}|{','.join(chosen)}"
        if key not in _cache:
            raw = gzip.decompress(path.read_bytes())
            people = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
            version = hashlib.sha256(raw).hexdigest()[:12]
            if chosen:
                people, version = _with_addons(people, version, chosen)
            while len(_cache) >= CACHE_MAX:  # topical add-on combinations vary by question; keep memory bounded
                _cache.pop(next(iter(_cache)))
            _cache[key] = (people, version)
        return _cache[key]  # type: ignore[return-value]


def _with_addons(people: list[dict], version: str, chosen: tuple[str, ...]) -> tuple[list[dict], str]:
    from pp import life_context

    raw = gzip.decompress(CONTEXT.read_bytes())
    rows = {r["uuid"]: r for r in (json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip())}
    missing = [p["uuid"] for p in people if p["uuid"] not in rows]
    if missing:
        raise ValueError(f"life context missing for {len(missing)} panel members")
    enriched = []
    for p in people:
        extra = life_context.block(rows[p["uuid"]], chosen)
        enriched.append({**p, "profile": p["profile"] + "\n\n" + extra} if extra else p)
    names = "all" if chosen == life_context.ALL_ADDONS else ".".join(chosen)
    return enriched, f"{version}+addons-{names}-{hashlib.sha256(raw).hexdigest()[:8]}"


def allocate(sizes: dict, n: int) -> dict:
    """Largest-remainder allocation of n seats proportional to stratum sizes."""
    total = sum(sizes.values())
    exact = {k: n * v / total for k, v in sizes.items()}
    seats = {k: int(x) for k, x in exact.items()}
    for k in sorted(exact, key=lambda k: (-(exact[k] - seats[k]), str(k)))[: n - sum(seats.values())]:
        seats[k] += 1
    return seats


def sample(people: list[dict], n: int, seed: int) -> list[dict]:
    """n people keeping the province × age band × sex proportions of the panel (deterministic for a seed)."""
    if n >= len(people):
        return list(people)
    strata: dict[tuple, list[dict]] = {}
    for p in sorted(people, key=lambda x: x["uuid"]):
        strata.setdefault((p["province"], p["age_band"], p["sex"]), []).append(p)
    seats = allocate({k: len(v) for k, v in strata.items()}, n)
    rng = random.Random(seed)
    return [p for key in sorted(strata, key=str) for p in rng.sample(strata[key], seats[key])]


def future_available() -> bool:
    return (os.environ.get("PP_PANEL_FUTURE") or "").strip() not in ("off", "none") and HISTORY.exists() and FORECAST.exists()


_future: tuple[dict, dict, str] | None = None  # kept apart from `_cache`, whose eviction follows add-on combinations


def _future_rows() -> tuple[dict, dict, str]:
    """(history by uuid, forecast by uuid, data version) — read once."""
    global _future
    with _lock:
        if _future is None:
            raw_h, raw_f = gzip.decompress(HISTORY.read_bytes()), gzip.decompress(FORECAST.read_bytes())
            rows = lambda raw: {r["uuid"]: r for r in (json.loads(x) for x in raw.decode("utf-8").splitlines() if x.strip())}  # noqa: E731
            version = hashlib.sha256(raw_h + raw_f).hexdigest()[:8]
            _future = (rows(raw_h), rows(raw_f), version)
        return _future


def states(people: list[dict]) -> dict[str, dict]:
    """Per member: {"now": 2025 state, "then": projected state or None, "alive": True / False (dead by then) / None (no
    forecast row)}, in `people` order. Read-only companion of future_pair for "대상 규칙으로 나눠 보기"."""
    from pp import life_history as lh

    hist, fc, _ = _future_rows()
    out = {}
    for p in people:
        row = fc.get(p["uuid"])
        then = (row or {}).get("baseline")
        alive = None if not then else bool(then.get("alive"))
        out[p["uuid"]] = {"now": lh.now_state(p, hist.get(p["uuid"], {})), "then": then if alive else None, "alive": alive}
    return out


def future_pair(people: list[dict], year: int | None = None) -> tuple[list[dict], list[dict], dict]:
    """The "5년 뒤 보기" pair for `people` (already carrying their add-ons): the same survivors with the base-year state
    block appended, and with their profile moved to the projected year. Members who die by then are left out.
    Returns (base_people, future_people, meta) with meta = {version, year, changes: {uuid: [changed states]}, dead}."""
    from pp import life_history as lh

    year = year or lh.FUTURE_YEAR
    hist, fc, version = _future_rows()
    base, future, changes, dead = [], [], {}, 0
    for p in people:
        then = (fc.get(p["uuid"]) or {}).get("baseline")
        if not then:
            continue
        if not then.get("alive"):
            dead += 1
            continue
        now = lh.now_state(p, hist.get(p["uuid"], {}))
        base.append({**p, "profile": p["profile"] + "\n\n" + lh.state_block(now, lh.BASE_YEAR, amount_year=lh.BASE_YEAR - 1)})
        future.append({**p, "profile": lh.future_profile(p, then, year)})
        changes[p["uuid"]] = lh.state_changes(now, then)
    return base, future, {"version": version, "year": year, "changes": changes, "dead": dead}
