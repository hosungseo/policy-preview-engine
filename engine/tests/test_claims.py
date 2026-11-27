"""Accuracy numbers written in the docs must come from a measurement record (EGM-style drift check).

Screens read the records at run time; prose does not, so a number in prose can go stale. Every "평균 … N%p"
claim in README.md and docs/service/*.md must equal a value in baseline.json, the historical baseline or a holdout
record, and when a holdout record exists README.md must also state its new-item error, so the optimistic figure
from already-seen items never stands alone.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "engine" / "ppservice" / "data"
CLAIM = re.compile(r"평균[^\n%]{0,30}?±?(?<![\d.])(\d+(?:\.\d+)?)\s*%p")


SKIP = {"items", "by_item", "age_gaps", "bands"}  # per-item detail; prose quotes summaries


def _numbers(obj) -> set[float]:
    found: set[float] = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in SKIP:
                continue
            if isinstance(value, (int, float)) and not isinstance(value, bool) and key.endswith("_pp"):
                found.add(float(value))
            else:
                found |= _numbers(value)
    elif isinstance(obj, list):
        for value in obj:
            found |= _numbers(value)
    return found


def recorded() -> set[float]:
    values: set[float] = set()
    for path in [DATA / "baseline.json", *sorted((DATA / "persona-accuracy").glob("historical-baseline-*.json")),
                 *sorted((DATA / "persona-accuracy").glob("holdout-*.json"))]:
        if path.exists():
            values |= _numbers(json.loads(path.read_text(encoding="utf-8")))
    return {round(v, 1) for v in values} | {float(round(v)) for v in values}


def claims() -> list[tuple[str, float]]:
    docs = [ROOT / "README.md", *sorted((ROOT / "docs" / "service").glob("*.md"))]
    return [(path.name, round(float(m.group(1)), 1)) for path in docs if path.exists()
            for m in CLAIM.finditer(path.read_text(encoding="utf-8"))]


def test_every_written_accuracy_number_has_a_record():
    known = recorded()
    stale = [(name, value) for name, value in claims() if value not in known]
    assert not stale, f"accuracy claims without a measurement record: {stale}"


def test_readme_states_the_unseen_item_error_when_measured():
    holdouts = sorted((DATA / "persona-accuracy").glob("holdout-*.json"))
    if not holdouts:
        return
    record = json.loads(holdouts[-1].read_text(encoding="utf-8"))
    new = {round(m["fwd"]["new"]["mae_pp"], 1) for m in record["models"].values() if m.get("fwd")}
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert any(f"{v}%p" in readme for v in new), f"README.md should state the unseen-item error (one of {sorted(new)})"
