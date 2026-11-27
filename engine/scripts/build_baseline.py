"""Offline baseline diagnostics from saved responses and frozen adult age weights.

Legacy calculations require --legacy and never overwrite the historical baseline.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


DATA = Path(__file__).resolve().parents[1] / "ppservice" / "data"
NEUTRAL_POLICY = "(이 문항은 특정 정책에 관한 것이 아닙니다.)"
SEED = 2024


def age_bounds(label: str) -> tuple[int, int | None]:
    match = re.fullmatch(r"(\d+)[–~∼-](\d+)세", label)
    if match:
        low, high = map(int, match.groups())
        if low <= high:
            return low, high
    match = re.fullmatch(r"(\d+)대", label)
    if match:
        low = int(match[1])
        return low, low + 9
    match = re.fullmatch(r"(\d+)세 이상", label)
    if match:
        return int(match[1]), None
    raise ValueError("invalid_age_band")


def band_of(person: dict, official_bands: list[str]) -> str | None:
    age = person["age"]
    if age < 20:
        return None
    return next((b for b in official_bands if age_bounds(b)[0] <= age
                 and (age_bounds(b)[1] is None or age <= age_bounds(b)[1])), None)


def legacy_band_of(person: dict, official_bands: list[str]) -> str | None:
    # Historical 19–29 label included only adults aged 20+.
    return band_of(person, official_bands)


def mean(rows: list[list[float]], k: int) -> list[float]:
    return [sum(r[i] for r in rows) / len(rows) for i in range(k)] if rows else [0.0] * k


def mae(a: list[float], b: list[float]) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def compare_legacy(item: dict, people: list[dict], answers: dict[str, list[float]]) -> dict:
    k = len(item["options"])
    official_bands = [b for b in item["age_bands"] if b != "60세 이상" or "60대" not in item["age_bands"]]
    if "60대" in item["age_bands"]:
        official_bands = [b for b in item["age_bands"] if b != "60세 이상"]
    off = {g: [item["groups"][g].get(o, 0.0) / 100 for o in item["options"]] for g in item["groups"]}
    bands: dict[str, list[list[float]]] = {}
    for p in people:
        b = legacy_band_of(p, official_bands)
        if b and p["uuid"] in answers:
            bands.setdefault(b, []).append(answers[p["uuid"]])
    syn_band = {b: mean(rows, k) for b, rows in bands.items()}
    weights = {b: len(rows) for b, rows in bands.items()}
    total = sum(weights.values())
    off_overall = [sum(off[b][i] * weights[b] for b in weights) / total for i in range(k)]
    syn_overall = mean([r for rows in bands.values() for r in rows], k)
    sexes = {s: mean([answers[p["uuid"]] for p in people if p["sex"] == s and p["age"] >= 20 and p["uuid"] in answers], k)
             for s in ("남자", "여자")}
    modal = max(range(k), key=lambda i: off_overall[i])
    order = [b for b in official_bands if b in syn_band]
    off_sd = statistics.pstdev([off[b][modal] for b in order])
    syn_sd = statistics.pstdev([syn_band[b][modal] for b in order])
    return {
        "id": item["id"], "title": item["title"], "question": item["question"], "period": item["period"],
        "options": item["options"], "n_answered": len(answers),
        "official_overall": [round(100 * x, 1) for x in off_overall],
        "synthetic_overall": [round(100 * x, 1) for x in syn_overall],
        "mae_overall_pp": round(100 * mae(syn_overall, off_overall), 1),
        "mae_band_pp": round(100 * statistics.mean(mae(syn_band[b], off[b]) for b in order), 1),
        "mae_sex_pp": round(100 * statistics.mean(mae(sexes[s], off[s]) for s in sexes), 1),
        "spread_ratio": round(syn_sd / off_sd, 2) if off_sd > 0 else None,
        "bands": {b: {"official": [round(100 * x, 1) for x in off[b]], "synthetic": [round(100 * x, 1) for x in syn_band[b]],
                      "n": weights[b]} for b in order},
    }


def summarize(items: list[dict], n: int, source: str, version: str, model: str, built: str | None = None) -> dict:
    """Headline numbers for the result screen. The worst single-option gap is shown next to the mean so a
    small average cannot hide one option that is far off."""
    spread = [i["spread_ratio"] for i in items if i["spread_ratio"] is not None]
    worst = max(items, key=lambda i: max(abs(a - b) for a, b in zip(i["synthetic_overall"], i["official_overall"])))
    gap = max(abs(a - b) for a, b in zip(worst["synthetic_overall"], worst["official_overall"]))
    return {
        "mae_pp": round(statistics.mean(i["mae_overall_pp"] for i in items), 1),
        "mae_max_pp": max(i["mae_overall_pp"] for i in items),
        "worst_option_gap_pp": round(gap), "worst_item": worst["title"],
        "mae_band_pp": round(statistics.mean(i["mae_band_pp"] for i in items), 1),
        "spread_ratio": round(statistics.median(spread), 2) if spread else None,
        "spread_min": min(spread) if spread else None, "spread_max": max(spread) if spread else None,
        "items": len(items), "n": n, "source": source, "panel_version": version, "jev_model": model,
        "built_at": built or time.strftime("%Y-%m-%d"),
    }


SCOPE_FIELDS = ("year", "unit", "population", "min_age", "max_age")


def scope_reason(actual: dict, expected: dict) -> str | None:
    for field in SCOPE_FIELDS:
        if field not in actual or actual[field] != expected[field]:
            return "scope_mismatch:" + field
    return None


def compare(item: dict, people: list[dict], answers: dict[str, list[float]], weights: dict | None = None,
            year: int = 2024, contexts: dict | None = None, include_sex: bool = True) -> dict:
    """Saved rows use item.options order; CLI requires matching source/response/weight scopes.

    Every scored cell declares scope, eligible, and options. sex_tables maps each
    sex to an item-shaped adult age cross-table plus its frozen `weights`.
    """
    definition = item.get("definition", {})
    if str(item["period"]) != str(year) or definition.get("year") != year:
        raise ValueError("year_mismatch")
    if (definition.get("unit") != "adult_person" or definition.get("min_age") != 20
            or not definition.get("population") or "max_age" not in definition):
        raise ValueError("population_or_unit_mismatch")
    ids = [p["uuid"] for p in people]
    if len(set(ids)) != len(ids) or set(answers) - set(ids):
        raise ValueError("response_population_mismatch")
    options, bands = item["options"], item["age_bands"]
    k = len(options)
    if not k or len(set(options)) != k:
        raise ValueError("invalid_options")
    bounds = [age_bounds(b) for b in bands]
    for index, (low, high) in enumerate(bounds):
        if low < 20 or any(max(low, lo) <= min(high or math.inf, hi or math.inf)
                           for lo, hi in bounds[:index]):
            raise ValueError("overlapping_or_mislabeled_age_cells")
    result = {"id": item["id"], "title": item.get("title", item["id"]), "options": options,
              **{f: definition[f] for f in SCOPE_FIELDS},
              "comparison": "연령 표준화 비교", "mae_overall_pp": None, "worst_pp": None,
              "n_planned": len(people), "n_answered": len(answers),
              "n_adult_planned": sum(p['age'] >= 20 for p in people),
              "n_adult_answered": sum(p['age'] >= 20 and p['uuid'] in answers for p in people),
              "service_format_eligible": 2 <= k <= 5,
              "mae_sex_pp": None, "bands": {}, "excluded_reasons": [], "transformations": []}
    context_errors = []
    for name, context in (contexts or {}).items():
        reason = scope_reason(context, definition)
        if reason:
            context_errors.append(name + ":" + reason)
        if context.get("options") != options:
            context_errors.append(name + ":options_mismatch")
    if not weights:
        result["excluded_reasons"].append("fixed_weights_missing")
    elif (set(weights) != set(bands) or any(not math.isfinite(v) or v < 0 for v in weights.values())
          or abs(sum(weights.values()) - 1) > 1e-6):
        raise ValueError("invalid_fixed_weights")
    syn, off = [0.0] * k, [0.0] * k
    missing = not weights
    for band, (low, high) in zip(bands, bounds):
        cell = item.get("group_definitions", {}).get(band, {})
        expected = {**definition, "min_age": low, "max_age": high}
        reasons = list(context_errors)
        limit = definition["max_age"]
        if low < definition["min_age"] or (limit is not None and (high is None or high > limit)):
            reasons.append("age_range_outside_population")
        if cell.get("eligible") is not True:
            reasons.append("cell_ineligible")
        reason = scope_reason(cell, expected)
        if reason:
            reasons.append(reason)
        if cell.get("options") != options or set(item["groups"].get(band, {})) != set(options):
            reasons.append("options_mismatch")
        rows = [answers[p["uuid"]] for p in people if band_of(p, bands) == band and p["uuid"] in answers]
        for row in rows:
            if len(row) != k or any(not math.isfinite(v) or v < 0 or v > 1 for v in row) or abs(sum(row) - 1) > 1e-6:
                raise ValueError("invalid_probabilities")
        if not rows:
            reasons.append("empty_age_cell")
        official = [item["groups"].get(band, {}).get(o, 0) / 100 for o in options]
        total = sum(official)
        if any(not math.isfinite(v) or v < 0 or v > 1 for v in official) or abs(total - 1) > .001 + 1e-12:
            reasons.append("invalid_official_probabilities")
        if reasons:
            result["bands"][band] = {"mae_pp": None, "reason": reasons[0], "reasons": reasons}
            result["excluded_reasons"].extend(r + ":" + band for r in reasons)
            missing = missing or bool(weights and weights[band] > 0)
            continue
        official = [v / total for v in official]
        result["transformations"].append({"band": band, "original_sum": total,
                                          "operation": "proportional_normalization", "factor": 1 / total})
        predicted = mean(rows, k)
        result["bands"][band] = {"mae_pp": 100 * mae(predicted, official),
                                  "official": official, "synthetic": predicted,
                                  "worst_pp": 100 * max(abs(a-b) for a,b in zip(predicted, official)),
                                  "n": len(rows), "weight": weights.get(band) if weights else None, "reason": None}
        if weights:
            for i in range(k):
                syn[i] += weights[band] * predicted[i]
                off[i] += weights[band] * official[i]
    if not missing:
        result.update(mae_overall_pp=100 * mae(syn, off),
                      worst_pp=100 * max(abs(a-b) for a,b in zip(syn, off)),
                      synthetic_overall=syn, official_overall=off)
        valid_bands = [v for v in result["bands"].values() if v["mae_pp"] is not None]
        result["mae_band_pp"] = statistics.mean(v["mae_pp"] for v in valid_bands)
        modal = max(range(k), key=lambda i: off[i])
        observed_sd = statistics.pstdev(v["official"][modal] for v in valid_bands)
        predicted_sd = statistics.pstdev(v["synthetic"][modal] for v in valid_bands)
        result["spread_ratio"] = predicted_sd / observed_sd if observed_sd else None
        result["spread_option"] = options[modal]
        worst_index = max(range(k), key=lambda i: abs(syn[i]-off[i]))
        result["worst_option"] = options[worst_index]
        result["spread_definition"] = "공식 전체 최빈 선택지의 연령셀 간 표준편차: 합성/실측; 비가중 셀 표준편차"
        unsure = [i for i, option in enumerate(options) if option == "잘 모르겠다"]
        result["unsure_signed_pp"] = 100 * sum(syn[i]-off[i] for i in unsure) if unsure else None
        result["unsure_pp"] = abs(result["unsure_signed_pp"]) if unsure else None
        result["age_gaps"] = []
        for a, first in enumerate(bands):
            for second in bands[a+1:]:
                left, right = result["bands"][first], result["bands"][second]
                if left["mae_pp"] is None or right["mae_pp"] is None:
                    continue
                for index, option in enumerate(options):
                    actual = 100 * (left["official"][index] - right["official"][index])
                    predicted = 100 * (left["synthetic"][index] - right["synthetic"][index])
                    result["age_gaps"].append(dict(first=first, second=second, option=option,
                        official_pp=actual, synthetic_pp=predicted, error_pp=abs(predicted-actual),
                        ratio=predicted/actual if abs(actual) >= 3 else None))
    if include_sex:
        tables = item.get("sex_tables", {})
        if set(tables) != {"남자", "여자"}:
            result["excluded_reasons"].append("sex_adult_cross_table_missing")
        else:
            result["sexes"] = {}
            for sex, table in tables.items():
                selected = [p for p in people if p.get("sex") == sex]
                subset = {p["uuid"]: answers[p["uuid"]] for p in selected if p["uuid"] in answers}
                sex_contexts = {**(contexts or {}), "parent": {**definition, "options": options},
                                "sex_weights": table.get("weight_definition", {})}
                result["sexes"][sex] = compare(table, selected, subset, table.get("weights"), year,
                                                 sex_contexts, include_sex=False)
                result["excluded_reasons"].extend(sex + ":" + r for r in result["sexes"][sex]["excluded_reasons"])
            values = [v["mae_overall_pp"] for v in result["sexes"].values()]
            if all(v is not None for v in values):
                result["mae_sex_pp"] = statistics.mean(values)
    result['eligible'] = result['mae_overall_pp'] is not None
    result['sex_eligible'] = result['mae_sex_pp'] is not None
    return result


def main() -> int:
    from ppservice.persona_accuracy import canonical, read_json, file_hash, verified_sources
    ap = argparse.ArgumentParser(description="Offline comparison; never calls Jev.")
    ap.add_argument("--official", type=Path, required=True)
    ap.add_argument("--responses", type=Path, required=True, help="Saved JSON: people, answers keyed by question ID, model_version")
    ap.add_argument("--weights", type=Path, required=True, help="Frozen JSON: year, unit, min_age, by_question")
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--paired-responses", type=Path, help="Compare only UUIDs valid in both option orders")
    ap.add_argument("--legacy", action="store_true", help="Explicit historical calculation, separate output only")
    args = ap.parse_args()
    if args.out.exists() or args.out.resolve() in {p.resolve() for p in (args.official, args.responses, args.weights, args.sources)}:
        ap.error("기존 baseline.json은 보존해야 합니다.")
    official, raw, weights = [read_json(p) for p in (args.official, args.responses, args.weights)]
    if args.paired_responses:
        paired = read_json(args.paired_responses)
        if paired["people"] != raw["people"] or paired["model_version"] != raw["model_version"]:
            raise ValueError("paired_population_or_model_mismatch")
        for q, answers in raw["answers"].items():
            raw["answers"][q] = {u: p for u, p in answers.items() if u in paired["answers"].get(q, {})}
    if weights.get("year") != args.year or weights.get("unit") != "adult_person" or weights.get("min_age") != 20:
        raise ValueError("weight_scope_mismatch")
    sources = verified_sources(read_json(args.sources))
    items = []
    for item in official["items"]:
        source = sources.get(item["id"])
        if not source:
            items.append({"id": item["id"], "mae_overall_pp": None, "mae_sex_pp": None,
                          "excluded_reasons": ["source_unverified"]})
            continue
        if source["period"] != str(args.year):
            raise ValueError("source_year_mismatch")
        fn = compare_legacy if args.legacy else compare
        extra = {} if args.legacy else {"weights": weights["by_question"].get(item["id"]), "year": args.year, "contexts": {"source": {**item.get("source_definition", {}),
            "year": int(source["period"]), "unit": source["unit"], "population": source["population"],
            "options": source["category_codes"]},
            "responses": raw.get("definitions", {}).get(item["id"], {}),
            "weights": weights.get("definitions", {}).get(item["id"], {})}}
        items.append(fn(item, raw["people"], raw["answers"].get(item["id"], {}), **extra))
    out = {"version": "legacy" if args.legacy else "comparison-v2", "status": "incomplete",
           "model_version": raw.get("model_version"), "items": items,
           "mae_pp": None, "reason": "개발 진단 전용; 독립 검증 및 모델판 증거 미확보",
           "input_hashes": {name: file_hash(getattr(args, name)) for name in ("official", "responses", "weights", "sources")}}
    if args.paired_responses:
        out["input_hashes"]["paired_responses"] = file_hash(args.paired_responses)
    if not args.legacy and items and all(i["mae_overall_pp"] is not None for i in items):
        out.update(status="diagnostic_complete", mae_pp=statistics.mean(i["mae_overall_pp"] for i in items),
                   worst_pp=max(i["worst_pp"] for i in items))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(canonical(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
