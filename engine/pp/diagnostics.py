"""Automated diagnostics for synthetic survey responses and question reliability.

Pure Python, zero model calls. Implements four research-backed checks:
1. Pre-run question reliability alerts (Jia et al. 2026: many options, subjective feeling/self-assessment items).
2. Between-person dispersion compression (Pourtaheri & Zareei 2026; Jia et al. 2026).
3. Education/income variance overestimation via one-way eta-squared (Pourtaheri & Zareei 2026).
4. Post-run answer variability via normalized Shannon entropy (Jia et al. 2026) plus multi-dimensional
   accuracy metrics (JSD, ordinal NMD soft similarity, Informedness J, subgroup Equity DPI).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict

# Pre-run reliability thresholds (Jia et al. 2026)
MANY_OPTIONS_THRESHOLD = 4
SUBJECTIVE_TOPIC = re.compile(
    r"스트레스|만족|체감|불안|행복|기분|감정|우울|외로움|삶의 질|평소 얼마나|얼마나 자주|"
    r"여가|취미|신뢰하|신뢰도|자신감|주관적|전반적으로 어떻게 느끼"
)

# Post-run diagnostic thresholds
MIN_DIAGNOSTIC_N = 20
DISPERSION_SD_WARN = 0.08
DISPERSION_IQR_PP_WARN = 10.0
DISPERSION_CLUSTER_SHARE_WARN = 0.80

EDU_INCOME_SHARE_WARN = 0.45
EDU_INCOME_SINGLE_ETA2_WARN = 0.15
EDU_INCOME_MIN_AXIS_ETA2 = 0.04
EDU_INCOME_MIN_GAP_PP = 10.0
MIN_AXIS_TOTAL_ETA2 = 0.02
MIN_AXIS_GROUP_N = 10

HIGH_VARIABILITY_ENTROPY_WARN = 0.85

EDU_INCOME_CARD_CAUTION = (
    "AI는 실제 사람보다 학력·소득에 따른 차이를 크게 부풀리는 경향이 있습니다. "
    "현장에서는 다른 생활 여건과 섞여 있는지 함께 확인하시기 바랍니다."
)

_EDU_HEADER_MAP = {
    "무학": "중학교 졸업 이하",
    "초등학교": "중학교 졸업 이하",
    "중학교": "중학교 졸업 이하",
    "고등학교": "고등학교",
    "2~3년제 전문대학": "전문대학",
    "4년제 대학교": "대학 졸업 이상",
    "대학원": "대학 졸업 이상",
}


def _finding(code: str, level: str, message: str, hint: str = "", **extra) -> dict:
    item = {"code": code, "level": level, "message": message, "hint": hint}
    if extra:
        item.update(extra)
    return item


def question_reliability_findings(question: str, options: list[str]) -> list[dict]:
    """Pre-run question reliability alerts based on option count and subjective-feeling wording."""
    q = (question or "").strip()
    opts = [o.strip() for o in (options or []) if o and o.strip()]
    found: list[dict] = []
    if len(opts) >= MANY_OPTIONS_THRESHOLD:
        found.append(
            _finding(
                "reliability_many_options",
                "info",
                f"선택지가 {len(opts)}개로 많습니다. 선택지가 많을수록 합성 인물 오차가 커지기 쉽습니다.",
                "합성 결과는 참고용으로만 보고 실제 이용자 확인 비중을 높이세요.",
            )
        )
    hit = SUBJECTIVE_TOPIC.search(q)
    if hit:
        found.append(
            _finding(
                "reliability_subjective_topic",
                "info",
                f"주관적 체감·감정·자기평가 성격의 문항입니다(‘{hit.group(0)}’). 합성 인물 오차가 커지기 쉬운 유형입니다.",
                "주관적 체감 문항은 합성 인물로 단정하지 말고 실제 이용자 확인 비중을 높이세요.",
            )
        )
    return found


def _parse_profile_header(profile: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (profile or "").split("\n\n")[0].split("\n"):
        for part in line.split(" / "):
            if ": " in part:
                k, v = part.split(": ", 1)
                out[k.strip()] = v.strip()
    return out


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(len(sorted_vals) - 1, lo + 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _population_sd(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))


def normalized_entropy(shares: list[float]) -> float:
    """Normalized Shannon entropy H / log(k) in [0, 1]."""
    k = len(shares)
    if k <= 1:
        return 0.0
    total = sum(max(0.0, s) for s in shares)
    if total <= 0:
        return 0.0
    probs = [max(0.0, s) / total for s in shares]
    h = -sum(p * math.log(p) for p in probs if p > 0)
    return round(h / math.log(k), 4)


def eta_squared(values: list[float], groups: list[str | None], *, min_group_n: int = MIN_AXIS_GROUP_N) -> dict:
    """One-way ANOVA eta-squared (SS_between / SS_total) and max group-mean gap in percentage points."""
    by_g: dict[str, list[float]] = defaultdict(list)
    for v, g in zip(values, groups):
        if g is not None and str(g).strip():
            by_g[str(g).strip()].append(v)
    usable = {g: vs for g, vs in by_g.items() if len(vs) >= min_group_n}
    if len(usable) < 2:
        return {"eta2": None, "groups": len(usable), "n": sum(len(vs) for vs in usable.values()), "max_gap_pp": None}
    all_vals = [v for vs in usable.values() for v in vs]
    n = len(all_vals)
    grand = sum(all_vals) / n
    ss_total = sum((v - grand) ** 2 for v in all_vals)
    means = {g: sum(vs) / len(vs) for g, vs in usable.items()}
    ss_between = sum(len(vs) * (means[g] - grand) ** 2 for g, vs in usable.items())
    eta2 = round(ss_between / ss_total, 4) if ss_total > 1e-12 else 0.0
    hi_g = max(means, key=means.__getitem__)
    lo_g = min(means, key=means.__getitem__)
    max_gap_pp = round(100.0 * (means[hi_g] - means[lo_g]), 1)
    return {
        "eta2": eta2,
        "groups": len(usable),
        "n": n,
        "max_gap_pp": max_gap_pp,
        "high_group": hi_g,
        "low_group": lo_g,
    }


def _extract_person_axes(person: dict, context_row: dict | None = None) -> dict[str, str | None]:
    hdr = _parse_profile_header(person.get("profile", ""))
    age_band = person.get("age_band")
    sex = person.get("sex")
    if "region" in person and person["region"]:
        region = person["region"]
    elif "capital" in person and person["capital"] is not None:
        region = "수도권" if person["capital"] else "비수도권"
    else:
        region = person.get("province")

    raw_edu = person.get("education_level") or hdr.get("학력") or ""
    education = _EDU_HEADER_MAP.get(raw_edu, raw_edu) if raw_edu else None

    income = person.get("income")
    if income is None and context_row:
        income = context_row.get("income")
    if income is None:
        m = re.search(r"가구\s*연소득:\s*([^\n/]+)", person.get("profile", ""))
        if m:
            income = m.group(1).strip()

    return {
        "age_band": age_band,
        "sex": sex,
        "region": region,
        "education": education,
        "income": str(income) if income is not None else None,
    }


def diagnose_survey(
    spec: dict,
    people: list[dict],
    main_answers: dict[str, list[float]],
    *,
    context: dict[str, dict] | None = None,
    min_group_n: int = MIN_AXIS_GROUP_N,
) -> dict:
    """Run all automated diagnostics on a survey's per-person probability vectors.

    Returns a JSON-serializable report dict with `metrics`, `axes`, `warnings`, and `reliability_findings`.
    """
    options = spec.get("options") or []
    question = spec.get("question") or ""
    k = len(options)
    reliability = question_reliability_findings(question, options)

    by_uuid = {p["uuid"]: p for p in people}
    paired = [(by_uuid[u], probs) for u, probs in main_answers.items() if u in by_uuid and len(probs) == k and k > 0]
    n = len(paired)
    if n == 0:
        return {
            "n": 0,
            "metrics": {
                "between_person_sd": None,
                "rms_option_sd": None,
                "iqr_pp": None,
                "majority_clustering_share": None,
                "answer_variability": None,
                "edu_income_eta2_sum": None,
                "edu_income_share_of_explained": None,
            },
            "axes": {},
            "reliability_findings": reliability,
            "warnings": [],
        }

    mean_probs = [sum(probs[i] for _, probs in paired) / n for i in range(k)]
    top = max(range(k), key=lambda i: mean_probs[i])
    top_vals = [probs[top] for _, probs in paired]
    top_mean = mean_probs[top]

    between_sd = round(_population_sd(top_vals), 4)
    opt_sds = [_population_sd([probs[i] for _, probs in paired]) for i in range(k)]
    rms_sd = round(math.sqrt(sum(s * s for s in opt_sds) / k), 4)
    sorted_top = sorted(top_vals)
    iqr_pp = round(100.0 * (_quantile(sorted_top, 0.75) - _quantile(sorted_top, 0.25)), 1)
    cluster_share = round(sum(abs(v - top_mean) <= 0.05 for v in top_vals) / n, 4)
    variability = normalized_entropy(mean_probs)

    ctx = context or {}
    axes_values: dict[str, list[str | None]] = {name: [] for name in ("age_band", "sex", "region", "education", "income")}
    for p, _ in paired:
        extracted = _extract_person_axes(p, ctx.get(p["uuid"]))
        for name in axes_values:
            axes_values[name].append(extracted[name])

    axes_stats = {
        name: eta_squared(top_vals, groups, min_group_n=min_group_n)
        for name, groups in axes_values.items()
    }

    valid_eta2 = {name: st["eta2"] for name, st in axes_stats.items() if st["eta2"] is not None}
    total_eta2 = sum(valid_eta2.values())
    edu_eta2 = valid_eta2.get("education")
    inc_eta2 = valid_eta2.get("income")
    edu_inc_vals = [v for v in (edu_eta2, inc_eta2) if v is not None]
    edu_inc_sum = round(sum(edu_inc_vals), 4) if edu_inc_vals else None
    edu_inc_share = (
        round(sum(edu_inc_vals) / total_eta2, 4)
        if edu_inc_vals and total_eta2 >= MIN_AXIS_TOTAL_ETA2
        else None
    )

    warnings: list[dict] = []

    # 1. Dispersion compression warning
    if n >= MIN_DIAGNOSTIC_N and (
        between_sd < DISPERSION_SD_WARN
        or iqr_pp < DISPERSION_IQR_PP_WARN
        or cluster_share >= DISPERSION_CLUSTER_SHARE_WARN
    ):
        warnings.append(
            _finding(
                "dispersion_compression",
                "warn",
                f"응답 쏠림(분산 압축)이 감지되었습니다(사람 간 표준편차 {between_sd:.3f}, 사분위 폭 {iqr_pp:.1f}%p, "
                f"평균 ±5%p 이내 집중 비율 {round(cluster_share * 100)}%). 합성 응답이 비슷하게 뭉쳐 있어 집단 구분이 둔할 수 있습니다.",
                "평균 수치만 보고 안심하지 마시고, 현장 면담으로 실제 의견 분포 폭을 따로 확인하세요.",
            )
        )

    # 2. Education / income gap overestimation warning
    edu_gap = axes_stats["education"]["max_gap_pp"] or 0.0
    inc_gap = axes_stats["income"]["max_gap_pp"] or 0.0
    strong_edu_or_inc = (
        (edu_eta2 is not None and edu_eta2 >= EDU_INCOME_MIN_AXIS_ETA2)
        or (inc_eta2 is not None and inc_eta2 >= EDU_INCOME_MIN_AXIS_ETA2)
        or max(edu_gap, inc_gap) >= EDU_INCOME_MIN_GAP_PP
    )
    single_axis_spike = (
        (edu_eta2 is not None and edu_eta2 >= EDU_INCOME_SINGLE_ETA2_WARN)
        or (inc_eta2 is not None and inc_eta2 >= EDU_INCOME_SINGLE_ETA2_WARN)
    )
    if n >= MIN_DIAGNOSTIC_N and (
        single_axis_spike
        or (edu_inc_share is not None and edu_inc_share >= EDU_INCOME_SHARE_WARN and strong_edu_or_inc)
    ):
        share_pct = f"{round(edu_inc_share * 100)}%" if edu_inc_share is not None else "높음"
        warnings.append(
            _finding(
                "edu_income_overestimation",
                "warn",
                f"학력·소득 축 격차가 유난히 크게 나타났습니다(전체 축 설명력 중 학력·소득 비중 {share_pct}, "
                f"학력 최대 차 {edu_gap:.1f}%p, 소득 최대 차 {inc_gap:.1f}%p). "
                "AI는 실제 사람보다 학력·소득에 따른 차이를 크게 부풀리는 경향이 있습니다.",
                "고정관념이 만든 차이를 현장 1순위로 오해하지 않도록 다른 생활 여건과 섞여 있는지 함께 확인하세요.",
            )
        )

    # 3. Post-run high answer variability warning
    if n >= MIN_DIAGNOSTIC_N and k >= 2 and variability >= HIGH_VARIABILITY_ENTROPY_WARN:
        warnings.append(
            _finding(
                "high_answer_variability",
                "warn",
                f"응답이 여러 선택지에 넓게 흩어져 있습니다(정규화 엔트로피 {variability:.2f}). "
                "의견 변동성이 큰 문항은 합성 인물 오차가 커지기 쉽습니다.",
                "이 문항은 합성 결과에 의존하지 말고 실제 이용자 조사를 우선하세요.",
            )
        )

    return {
        "n": n,
        "top_option": options[top] if k else None,
        "metrics": {
            "between_person_sd": between_sd,
            "rms_option_sd": rms_sd,
            "iqr_pp": iqr_pp,
            "majority_clustering_share": cluster_share,
            "answer_variability": variability,
            "edu_income_eta2_sum": edu_inc_sum,
            "edu_income_share_of_explained": edu_inc_share,
        },
        "axes": axes_stats,
        "reliability_findings": reliability,
        "warnings": warnings,
    }


def diagnose_jev_rows(
    rows: list[dict],
    people: dict[str, dict],
    *,
    context: dict[str, dict] | None = None,
    question: str = "",
    options: list[str] | None = None,
    min_group_n: int = MIN_AXIS_GROUP_N,
) -> dict:
    """Adapter for deep-analysis Jev quantitative rows (`stance_probs` over 5 levels)."""
    opts = options or ["강하게 반대", "반대", "보통·유보", "찬성", "강하게 찬성"]
    main = {r["uuid"]: r["stance_probs"] for r in rows if r.get("uuid") in people and r.get("stance_probs")}
    person_list = [people[u] for u in main]
    return diagnose_survey(
        {"question": question, "options": opts},
        person_list,
        main,
        context=context,
        min_group_n=min_group_n,
    )


def format_warnings_markdown(diag: dict) -> str:
    """Render pre-run reliability alerts and post-run diagnostic warnings as Markdown bullets."""
    lines: list[str] = []
    for item in diag.get("reliability_findings", []):
        lines.append(f"- **[사전 경보 · {item['code']}]** {item['message']}" + (f" ({item['hint']})" if item.get("hint") else ""))
    for item in diag.get("warnings", []):
        lines.append(f"- **[자동 진단 경고 · {item['code']}]** {item['message']}" + (f" ({item['hint']})" if item.get("hint") else ""))
    if not lines:
        return "- 자동 진단에서 감지된 특이 경고가 없습니다."
    return "\n".join(lines)


# ---- Multi-dimensional accuracy metrics (gemini.md #3) ----

def _normalize_dist(dist: list[float]) -> list[float]:
    vals = [max(0.0, float(x)) for x in dist]
    total = sum(vals)
    if total <= 0:
        raise ValueError("distribution sum must be positive")
    return [v / total for v in vals]


def jsd(p: list[float], q: list[float]) -> float:
    """Jensen-Shannon Divergence (base 2), bounded in [0, 1]."""
    if len(p) != len(q) or not p:
        raise ValueError("distributions must have the same non-empty length")
    pn, qn = _normalize_dist(p), _normalize_dist(q)
    m = [0.5 * (a + b) for a, b in zip(pn, qn)]
    kl_pm = sum(a * math.log2(a / c) for a, c in zip(pn, m) if a > 0 and c > 0)
    kl_qm = sum(b * math.log2(b / c) for b, c in zip(qn, m) if b > 0 and c > 0)
    return round(0.5 * (kl_pm + kl_qm), 6)


def nmd_soft_similarity(p: list[float], q: list[float]) -> float:
    """Ordinal Soft Similarity = 1 - EMD / (k - 1), in [0, 1] (Morocho et al. 2026)."""
    if len(p) != len(q) or len(p) < 2:
        raise ValueError("ordinal distributions must have the same length >= 2")
    pn, qn = _normalize_dist(p), _normalize_dist(q)
    cdf_p = 0.0
    cdf_q = 0.0
    emd = 0.0
    for a, b in zip(pn[:-1], qn[:-1]):
        cdf_p += a
        cdf_q += b
        emd += abs(cdf_p - cdf_q)
    sim = max(0.0, min(1.0, 1.0 - emd / (len(pn) - 1)))
    return round(sim, 6)


def informedness_j(y_true: list, y_pred: list) -> float:
    """Youden's Informedness J = TPR + TNR - 1 (macro-averaged one-vs-rest for multiclass)."""
    if len(y_true) != len(y_pred) or not y_true:
        raise ValueError("y_true and y_pred must have the same non-empty length")
    labels = sorted(set(y_true) | set(y_pred), key=str)
    if len(labels) < 2:
        return 0.0
    scores: list[float] = []
    for cls in labels:
        tp = sum(t == cls and p == cls for t, p in zip(y_true, y_pred))
        fn = sum(t == cls and p != cls for t, p in zip(y_true, y_pred))
        tn = sum(t != cls and p != cls for t, p in zip(y_true, y_pred))
        fp = sum(t != cls and p == cls for t, p in zip(y_true, y_pred))
        if (tp + fn) == 0 or (tn + fp) == 0:
            continue
        tpr = tp / (tp + fn)
        tnr = tn / (tn + fp)
        scores.append(tpr + tnr - 1.0)
    return round(sum(scores) / len(scores), 6) if scores else 0.0


def equity_dpi(group_errors: dict[str, float]) -> dict:
    """Subgroup Equity Disparity Index: gap between worst and best subgroup error (Morocho et al. 2026)."""
    if not group_errors:
        return {"dpi": None, "worst_group": None, "best_group": None, "worst_error": None, "best_error": None}
    worst = max(group_errors, key=group_errors.__getitem__)
    best = min(group_errors, key=group_errors.__getitem__)
    return {
        "dpi": round(float(group_errors[worst]) - float(group_errors[best]), 6),
        "worst_group": worst,
        "best_group": best,
        "worst_error": round(float(group_errors[worst]), 6),
        "best_error": round(float(group_errors[best]), 6),
    }
