"""Opt-in, zero-model cohort baselines with explicit publication-time cutoffs.

These are aggregate historical references, never synthetic-person responses.
No network, model weights, or automatic question matching is used here.
"""
from __future__ import annotations

from datetime import date
import math


METHODS = ("last", "linear")


def _date(value):
    if not isinstance(value, str):
        raise ValueError("date_required")
    return date.fromisoformat(value)


def _vector(values, size):
    if not isinstance(values, list) or len(values) != size or size < 2:
        raise ValueError("distribution_shape")
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in values):
        raise ValueError("invalid_probability")
    total = sum(values)
    if abs(total - 1) > .002:
        raise ValueError("distribution_sum")
    return [v / total for v in values]


def predict(rows, *, question_id, group, definition_id, target_year, as_of, method="last"):
    """Use only matching rows published by as_of and surveyed before target_year.

definition_id must identify the exact question wording, options, population,
and group boundaries. It is caller-reviewed, not inferred from similar text.
"""
    if method not in METHODS:
        raise ValueError("unknown_trend_method")
    if any(not isinstance(v, str) or not v.strip() for v in (question_id, group, definition_id)):
        raise ValueError("exact_definition_required")
    cutoff = _date(as_of)
    if type(target_year) is not int or target_year <= cutoff.year:
        raise ValueError("target_must_be_after_cutoff_year")
    selected = []
    for row in rows:
        if (row.get("question_id"), row.get("group"), row.get("definition_id")) != (
                question_id, group, definition_id):
            continue
        year = row.get("year")
        if type(year) is not int:
            raise ValueError("year_required")
        if year >= target_year:
            continue
        # Publication, rather than only the observation year, determines availability.
        released = _date(row.get("released_at"))
        if released > cutoff:
            continue
        observed = _date(row.get("fieldwork_end"))
        if observed > released or observed.year != year:
            raise ValueError("invalid_observation_date")
        if observed > cutoff:
            continue
        selected.append(row)
    selected.sort(key=lambda r: r["year"])
    if not selected:
        raise ValueError("no_available_history")
    if len({r["year"] for r in selected}) != len(selected):
        raise ValueError("duplicate_year_requires_vintage_selection")
    options = selected[-1]["options"]
    if (not isinstance(options, list) or not all(isinstance(o, str) and o for o in options)
            or len(set(options)) != len(options)):
        raise ValueError("invalid_options")
    if any(r["options"] != options for r in selected):
        raise ValueError("option_definition_changed")
    for row in selected:
        if not isinstance(row.get("source_url"), str) or not row["source_url"].startswith("https://"):
            raise ValueError("source_required")
        _vector(row["probabilities"], len(options))
    used = selected[-1:] if method == "last" else selected[-2:]
    if method == "linear" and len(used) < 2:
        raise ValueError("two_history_years_required")
    values = _vector(used[-1]["probabilities"], len(options))
    if method == "linear":
        previous = _vector(used[0]["probabilities"], len(options))
        scale = (target_year - used[-1]["year"]) / (used[-1]["year"] - used[0]["year"])
        values = [max(0., min(1., v + scale * (v - old))) for v, old in zip(values, previous)]
        total = sum(values)
        values = [v / total for v in values]
    return {"kind": "historical_trend_baseline", "label": "과거 추세 기준선",
            "method": method, "question_id": question_id, "group": group,
            "definition_id": definition_id, "target_year": target_year, "as_of": as_of,
            "options": options, "probabilities": values,
            "history_years": [r["year"] for r in used],
            "history_sources": [{k: r[k] for k in ("year", "released_at", "source_url")} for r in used],
            "cost_usd": 0, "model_calls": 0,
            "notice": "공개 집계의 과거 추세입니다. 합성 인물 응답이나 실제 여론 예측의 검증값이 아닙니다."}


def distribution_error(predicted, actual):
    """MAE in percentage points and squared distribution distance, not Brier score."""
    size = len(actual)
    p, q = _vector(predicted, size), _vector(actual, size)
    return {"mae_pp": 100 * sum(abs(a - b) for a, b in zip(p, q)) / size,
            "worst_pp": 100 * max(abs(a - b) for a, b in zip(p, q)),
            "squared_distribution_error": sum((a - b) ** 2 for a, b in zip(p, q))}
