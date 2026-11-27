"""Computed synthetic distributions and offline slices; never infer missing archive data."""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import math
import os
from datetime import date

from . import budget, config, jev, mcp_setup, public_rules, visit_shared

SCHEMA = "pp.run/4"
DEFAULT_DECISION_SAMPLE = 3000
MAX_DECISION_SAMPLE = 5000
STANCES = ("support", "oppose", "unknown")
NOTICE = "합성 인물 모의 응답(실제 사람 0명)입니다. 여론조사가 아니며, 먼저 찾아갈 집단과 질문을 고르는 참고값입니다."
UNKNOWN_NOTICE = "모의 응답의 '모름' 비율은 실제 유보율과 크게 다를 수 있습니다."
MISSING_NOTICE = "19세 미만, 외국인 주민, 이해단체·기관의 조직된 의견은 합성 명단에 없어 별도 현장 확인이 필요합니다."
UNSTABLE_NOTICE = "선택지 순서나 대조 문장만 바꿔도 결과가 흔들립니다. 이 문항의 숫자는 방향 참고로 쓰기 어렵습니다. 문항을 다듬어 다시 실행하세요."


def baseline_for(policy_text, baseline):
    """Accept only a pp trend artifact and an explicitly reviewed exact definition."""
    if baseline is None:
        return None
    def require(condition):
        if not condition:
            raise ValueError("baseline definition mismatch")
    try:
        definition = baseline["definition"]
        require(definition["confirmed"] is True and definition["policy_text"] == policy_text)
        require(definition["population"] == "대한민국 19세 이상" and definition["group_boundaries"] == "전체")
        require(baseline["group"] in {"all", "전체"})
        require(all(definition[k] == baseline[k] and baseline[k] for k in ("question_id", "definition_id", "group", "options")))
        require(baseline["kind"] == "historical_trend_baseline" and baseline["method"] in {"last", "linear"})
        require(baseline["cost_usd"] == baseline["model_calls"] == 0)
        keys = definition["stance_keys"]
        require(len(keys) == 3 and set(keys) == set(STANCES) and len(baseline["options"]) == 3)
        values = baseline["probabilities"]
        require(len(values) == 3 and all(type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 1 for v in values))
        require(abs(sum(values) - 1) <= .002)
        cutoff = date.fromisoformat(baseline["as_of"])
        require(type(baseline["target_year"]) is int and baseline["target_year"] > cutoff.year)
        sources = baseline["history_sources"]
        require(sources and all(date.fromisoformat(s["released_at"]) <= cutoff and s["year"] < baseline["target_year"] and s["source_url"].startswith("https://") for s in sources))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("baseline requires an exact, confirmed policy/options/population/group definition and a pp trend artifact") from None
    return {**deepcopy(baseline), "available": True, "rates": dict(zip(keys, values)),
            "notice": "과거 공개 집계의 추세이며, 현재 여론이나 합성 응답의 정답이 아닙니다."}


def decision_sample(value=None):
    if value is None:
        raw = os.environ.get("PP_DECISION_SAMPLE", str(DEFAULT_DECISION_SAMPLE))
        try:
            value = int(raw)
        except ValueError:
            raise ValueError("decision_sample must be an integer from 1 to 5000") from None
    if type(value) is not int or not 1 <= value <= MAX_DECISION_SAMPLE:
        raise ValueError("decision_sample must be an integer from 1 to 5000")
    return value


def enabled(credentials=None):
    if mcp_setup.mock_mode():
        return True
    if jev.provider() == "mock":
        return True
    # Request-local TypeSafe credentials take precedence; Solar Decide uses its own key.
    if credentials is not None and jev.provider() != "upstage":
        return bool(credentials.typesafe)
    return jev.available()


def plan(policy_text, sample, requested, credentials=None):
    active = enabled(credentials)
    n = decision_sample(requested)
    mock = mcp_setup.mock_mode() or jev.provider() == "mock"
    # Three typed questions per persona (base, control wording, reversed options).
    tokens = n * (len(policy_text) + 2200) if active else 0
    usd = 0 if mock else tokens * jev.price_per_m_input() / 1_000_000
    return {"available": active, "requested_n": n, "n": n if active else 0,
            "model": "mock" if mock else jev.model(), "provider": "mock" if mock else jev.provider(),
            "input_tokens": tokens, "estimated_cost_usd": {"low": round(usd * .5, 4), "high": round(usd * 2, 4)},
            "fallback": not active, "fallback_sample": sample if not active else None,
            "checks": ["control_wording", "reversed_options"] if active else [],
            "notice": "화면 구조 확인용 가짜 숫자(0원 체험)입니다. 결과 수치에 뜻이 없습니다." if mock else "확률 평균 분포이며 실제 사람 응답이 아닙니다." if active else
                f"판단 모델 없이 문장 모델 소표본(최대 {sample}명)으로 대체합니다. 분포가 한쪽으로 쏠릴 수 있어 방향 참고만 하세요."}


def metadata(person):
    province = config.to_raw_province(person.get("province", "")) or person.get("province", "")
    return {"id": person["uuid"], "panel": "affected" if person.get("panel") == "aff" or person.get("kind") == "affected" else "representative",
            "age": int(person["age"]), "age_band": config.age_band(int(person["age"])),
            "province": province, "region": config.REGION_OF.get(province, province), "sex": person.get("sex", "")}


def reaction_rows(people, reactions):
    by_id = {p["uuid"]: p for p in people}
    rows = []
    for reaction in reactions:
        if reaction["uuid"] not in by_id:
            continue
        stance = "support" if reaction["support"] > 0 else "oppose" if reaction["support"] < 0 else "unknown"
        rows.append({**metadata(by_id[reaction["uuid"]]), "stance": stance,
                     "probabilities": {k: float(k == stance) for k in STANCES},
                     "reason": public_rules.check_output(reaction.get("reason", ""), "", []),
                     "source": "sentence_model"})
    return rows


def judge(policy_text, people):
    criteria = {"support": "찬성 쪽", "oppose": "반대 쪽", "unknown": "모름·유보: 정보 부족 또는 입장 미정"}
    def one(person):
        questions = {
            "base": {"type": "choice", "criteria": criteria, "instructions": "이 정책안에 대한 입장은 무엇인가요?"},
            "control": {"type": "choice", "criteria": criteria, "instructions": "이 정책안의 시행에 찬성하는지, 반대하는지, 아직 판단하기 어려운지 골라 주세요."},
            "reversed": {"type": "choice", "criteria": dict(reversed(list(criteria.items()))), "instructions": "이 정책안에 대한 입장은 무엇인가요?"},
        }
        # Redact synthetic names before external transmission, matching the reason stage.
        profile = public_rules.PERSON.sub("이 집단의 구성원", person.get("profile", person.get("persona", "")))
        answers = jev.evaluate({"persona": profile, "policy": policy_text}, questions, label="fast_distribution")["answers"]
        vectors = {}
        for key, answer in answers.items():
            p = answer.get("probabilities", {})
            if set(p) != set(STANCES) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in p.values()) or not .998 <= sum(p.values()) <= 1.002:
                raise jev.JevError("invalid stance probabilities")
            vectors[key] = {k: p[k] / sum(p.values()) for k in STANCES}
        return {**metadata(person), "probabilities": vectors["base"], "control": vectors["control"],
                "reversed": vectors["reversed"], "stance": max(STANCES, key=vectors["base"].get), "source": "decision_model"}
    workers = budget.current().limits.max_concurrency if budget.current() else 8
    with budget.ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, people))


def distribution(rows):
    n = len(rows)
    counts = {k: sum(r["probabilities"][k] for r in rows) for k in STANCES}
    return {"n": n, "counts": {k: round(v, 4) for k, v in counts.items()},
            "count_kind": "expected" if any(r.get("source") == "decision_model" for r in rows) else "selected",
            "count_notice": "판단 모델의 확률 합계는 추정 인원이며 정수 선택 건수가 아닙니다.",
            "rates": {k: counts[k] / n for k in STANCES} if n >= 5 else None,
            "small_group": n < 100, "rates_hidden": n < 5,
            "warning": (
                "해석 불가(표본 극소)" if n < 5 else "소집단 주의: 인원이 적어 집단 특성으로 단정할 수 없습니다(현장 확인 참고용)." if n < 30 else "표본 여유 부족" if n < 100 else None)}


def variability(rows):
    matched = [r for r in rows if "control" in r and "reversed" in r]
    if not matched:
        return {"available": False, "width_pp": None, "control_pp": None, "order_pp": None,
                "unstable": False, "notice": "대조 문장·선택지 순서 흔들림을 측정하지 않았습니다. 통계적 표본오차가 아닙니다."}
    n = len(matched)
    changes = {key: 100 * max(abs(sum(r[key][k] - r["probabilities"][k] for r in matched) / n) for k in STANCES)
               for key in ("control", "reversed")}
    width = max(3., *changes.values())
    return {"available": True, "n": n, "width_pp": round(width, 4), "control_pp": round(changes["control"], 4),
            "order_pp": round(changes["reversed"], 4), "floor_pp": 3., "unstable": width > 7,
            "warning_code": "UNSTABLE_PP" if width > 7 else None,
            "notice": UNSTABLE_NOTICE if width > 7 else "대조 문장·선택지 순서 변화 중 큰 값(최소 3.0%p)입니다. 통계적 표본오차가 아닙니다."}


def build(rows, *, population=None, decision=None, reason_n=0, baseline=None):
    # A UUID contributes once within each purpose-specific panel.
    rows = list({(r["panel"], r["id"]): r for r in rows}.values())
    rep = [r for r in rows if r["panel"] == "representative"]
    aff = [r for r in rows if r["panel"] == "affected"]
    base = distribution(rep)
    wobble = variability(rep)
    groups, highlights = {}, []
    for key in ("age_band", "region", "province", "sex"):
        groups[key] = []
        for panel, members, overall in (("representative", rep, base), ("affected", aff, distribution(aff))):
            acc = defaultdict(list)
            for row in members:
                acc[row[key]].append(row)
            for group, subset in sorted(acc.items()):
                dist = distribution(subset)
                var = variability(subset)
                delta = {s: 100 * (dist["rates"][s] - overall["rates"][s]) for s in STANCES} if dist["rates"] and overall["rates"] else None
                # Conservative descriptive comparison guard, not a confidence interval.
                threshold = ((wobble["width_pp"] or 0) + (var["width_pp"] or 0) + 100 / math.sqrt(len(subset))) if wobble["available"] and var["available"] else None
                item = {"group": group, "panel": panel, **dist, "delta_pp": delta, "variability": var,
                        "comparison_threshold_pp": threshold,
                        "highlight": panel == "representative" and len(subset) >= 100 and threshold is not None and not wobble["unstable"] and not var["unstable"] and max(abs(v) for v in delta.values()) > threshold}
                groups[key].append(item)
                if item["highlight"]:
                    people = [{"age": r["age"], "province": r["province"], "profile": "", "occupation": ""} for r in subset]
                    outreach = visit_shared.venue_guidance(group, people)
                    highlights.append({"dimension": key, **item, "outreach": outreach,
                                       "basis": "전체 대비 차이가 집단·전체 흔들림과 인원 기준을 합친 비교 기준을 넘는 현장 확인 후보입니다."})
    return {"numeric_notice": NOTICE, "overall": {**base, "panel": "representative", "population": population,
            "sampling": "province_age_sex_stratified", "representative": base,
            "affected": {**distribution(aff), "panel": "affected", "notice": "비대표 영향권이며 전체 비율에 합산하지 않습니다."},
            "variability": wobble, "decision": decision, "reason_sample_n": reason_n,
            "unknown_notice": UNKNOWN_NOTICE, "missing_notice": MISSING_NOTICE},
            "by_group": groups, "highlights": highlights,
            "baseline": deepcopy(baseline) if baseline else {"available": False, "notice": "동일 문항 과거 공개 기준선 없음"},
            "slice_data": {"schema": "pp.slice/1", "rows": rows, "scope": "returned_results_only"}}


def slice_results(result, filters=None, reason_limit=3):
    """Reaggregate supplied observations only. No model, DB, network, or extrapolation."""
    if not isinstance(result, dict) or not isinstance(filters or {}, dict):
        raise ValueError("result and filters must be objects")
    filters = filters or {}
    allowed = {"age_min", "age_max", "age_band", "region", "province", "sex", "stance", "panel"}
    if filters.keys() - allowed or type(reason_limit) is not int or not 0 <= reason_limit <= 10:
        raise ValueError("invalid slice options")
    for k in ("age_min", "age_max"):
        if k in filters and (type(filters[k]) is not int or not 0 <= filters[k] <= 130):
            raise ValueError("invalid age")
    if filters.get("age_min", 0) > filters.get("age_max", 130):
        raise ValueError("invalid age range")
    if any(not isinstance(v, str) for k, v in filters.items() if k not in {"age_min", "age_max"}):
        raise ValueError("invalid filter value")
    panel = filters.get("panel", "representative")
    if panel not in {"representative", "affected"} or ("stance" in filters and filters["stance"] not in STANCES):
        raise ValueError("invalid panel or stance")
    data = result.get("result", result)
    sliced = data.get("slice_data", {})
    if sliced.get("schema") != "pp.slice/1":
        raise ValueError("slice data unavailable; retrieve full result")
    def matches(r):
        return (r["panel"] == panel and r["age"] >= filters.get("age_min", 0) and r["age"] <= filters.get("age_max", 130)
                and all(r.get(k) == (config.to_raw_province(v) or v if k == "province" else v)
                        for k, v in filters.items() if k not in {"age_min", "age_max", "panel"}))
    rows = [r for r in sliced["rows"] if matches(r)]
    reasons = [r for r in sliced.get("reason_rows", sliced["rows"]) if matches(r) and r.get("reason")]
    # Enforce the same four small-group tiers and instability signals in every slice.
    return public_rules.envelope({"schema": "pp.slice/1", "numeric_notice": NOTICE, "panel": panel,
            **{k: data[k] for k in ("mode", "trial_notice", "result_label", "archive") if k in data},
            "filters": filters, **distribution(rows), "variability": variability(rows),
            "reasons": [{"id": r["id"], "stance": r["stance"], "reason": r["reason"], "source": r["source"]} for r in reasons[:reason_limit]],
            "reason_notice": "이유는 별도 문장 모델 소표본이며 판단 모델 분포의 개인별 이유로 단정할 수 없습니다.",
            "source_scope": sliced.get("scope"), "cost_usd": 0, "model_calls": 0,
            "highlight": False, "warnings": [UNKNOWN_NOTICE, *(["보관된 이유 소표본 재집계이며 Jev 전체 분포가 아닙니다."] if sliced.get("scope") == "archived_reason_sample" else [])]})


def from_archive(data):
    """Use the saved Jev mass verbatim; a mean alone cannot recover group stances."""
    analysis = data["analysis"]
    reasons = reaction_rows(data["personas"], data["reactions"])
    result = build(reasons, population=data.get("population", {}).get("total"), reason_n=len(reasons),
                   decision={"available": bool(analysis.get("jev")), "model": "Jev", "archived": True})
    quant = analysis.get("jev")
    if quant:
        original = quant["overall"]
        mass, n = original["mass"], original["n"]
        rates = {"support": mass[3] + mass[4], "oppose": mass[0] + mass[1], "unknown": mass[2]}
        dist = {"n": n, "rates": rates, "counts": {k: round(v * n, 4) for k, v in rates.items()},
                "count_kind": "expected", "small_group": n < 100, "rates_hidden": n < 5, "warning": None}
        result["overall"].update({**dist, "representative": dist, "source": "archived_jev_probability_mean", "original_mass": mass})
        for key, groups in quant.get("by_group", {}).items():
            affected = [g for g in result["by_group"].get(key, []) if g["panel"] == "affected"]
            result["by_group"][key] = [{"group": g["group"], "panel": "representative", "n": g["n"],
                "counts": None, "rates": None, "delta_pp": None, "count_kind": "unavailable",
                "variability": variability([]), "comparison_threshold_pp": None,
                "rates_hidden": True, "small_group": g["n"] < 100, "highlight": False,
                "warning": "해석 불가(표본 극소)" if g["n"] < 5 else "소집단 주의" if g["n"] < 30 else "표본 여유 부족" if g["n"] < 100 else None,
                "availability_notice": "보관 집단별 평균 점수만으로 찬반 분포를 복원할 수 없습니다.",
                "archived_mean": g.get("mean")} for g in groups] + affected
    result["overall"]["variability"] = {"available": False, "width_pp": None, "control_pp": None, "order_pp": None,
        "unstable": False, "notice": "보관된 반복·배치·쟁점 순서 지표는 전체 찬반의 대조 문장·선택지 순서 흔들림 측정값이 아닙니다."}
    result["slice_data"]["scope"] = "archived_reason_sample"
    result["highlights"] = []
    return result
