"""Optional 3-arm persona net-effect comparison (gemini.md #1/#5, grok.md #5).

Asks the exact same policy + question + options in three modes:
  (a) no_persona        -- Vanilla baseline with no persona profile at all.
  (b) manual_conditions -- Small set of hand-written condition cards written by a policy officer.
  (c) synthetic_personas -- Synthetic personas sampled from the Nemotron-based panel.

Produces a structured JSON report and Markdown comparison table including:
  - Persona net lift vs no-persona (PB - V) and vs manual conditions
  - Automated diagnostics warnings (dispersion compression, edu/income gap inflation, reliability alerts)
  - "새로 고칠 문제가 늘었을 때만 확대" (expand only when new actionable problems increase) decision panel.

Keep core pipeline untouched: this module is completely standalone and mock-safe (0 won by default).
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import budget, diagnostics, jev

NOISE_FLOOR_PP = 3.0
UNDECIDED_TOKENS = ("모르", "모름", "의견 없", "무응답")
DEFAULT_INSTRUCTIONS = (
    "Answer the survey question in `question` as this person would, after reading the policy in "
    "`policy`. Pick the option they would most likely choose."
)
NO_PERSONA_INSTRUCTIONS = (
    "Answer the survey question in `question` after reading the policy in `policy`. "
    "Pick the most reasonable option without assuming any specific persona."
)

# Starter hand-written conditions (a small officer-authored set for comparing against synthetic personas).
DEFAULT_MANUAL_CONDITIONS: list[dict] = [
    {
        "id": "manual-1",
        "label": "고령 1인 가구(비디지털)",
        "profile": "성별·나이: 여자, 74세 / 가구: 혼자 거주 / 생활 여건: 스마트폰 앱 신청이 익숙하지 않아 행정복지센터 방문을 선호함",
    },
    {
        "id": "manual-2",
        "label": "맞벌이·자녀 양육 가구",
        "profile": "성별·나이: 남자, 38세 / 가구: 배우자·자녀와 거주 / 생활 여건: 평일 낮 방문이 어렵고 야간·온라인 안내가 필요함",
    },
    {
        "id": "manual-3",
        "label": "비수도권 자영업자",
        "profile": "성별·나이: 남자, 52세 / 사는 곳: 비수도권 / 직업: 소규모 상점 경영자 / 생활 여건: 영업시간 중 이동과 서류 준비 부담이 큼",
    },
    {
        "id": "manual-4",
        "label": "청년 월세 1인 가구",
        "profile": "성별·나이: 여자, 25세 / 가구: 혼자 거주 / 주거: 월세 / 생활 여건: 제도 이름을 미리 알지 못해 쉬운 첫 안내가 필요함",
    },
    {
        "id": "manual-5",
        "label": "저소득·임시근로 가구",
        "profile": "성별·나이: 여자, 47세 / 고용: 비정규·단기 근로 / 생활 여건: 소득 증빙 서류 발급과 예외 기준 확인이 어려움",
    },
]


def _option_keys(options: list[str]) -> list[str]:
    return [f"o{i + 1}" for i in range(len(options))]


def _is_undecided(option: str) -> bool:
    compact = option.replace(" ", "")
    return any(tok.replace(" ", "") in compact for tok in UNDECIDED_TOKENS)


def _questions_payload(options: list[str], *, reverse: bool = False, no_persona: bool = False) -> dict:
    pairs = list(zip(_option_keys(options), options))
    if reverse:
        pairs = [p for p in pairs if not _is_undecided(p[1])][::-1] + [p for p in pairs if _is_undecided(p[1])]
    instructions = NO_PERSONA_INSTRUCTIONS if no_persona else DEFAULT_INSTRUCTIONS
    return {"q": {"type": "choice", "criteria": dict(pairs), "instructions": instructions}}


def _normalize_probs(probs: dict, keys: list[str]) -> list[float]:
    values = [max(0.0, float(probs.get(k, 0.0))) for k in keys]
    total = sum(values)
    if total <= 0:
        raise ValueError("no probability mass returned")
    return [round(v / total, 6) for v in values]


def _mean_shares(rows: list[list[float]], k: int) -> list[float]:
    if not rows:
        return [0.0] * k
    return [sum(r[i] for r in rows) / len(rows) for i in range(k)]


def _int_percent(shares: list[float]) -> list[int]:
    total = sum(shares) or 1.0
    exact = [100.0 * s / total for s in shares]
    floor = [int(x) for x in exact]
    for i in sorted(range(len(exact)), key=lambda idx: -(exact[idx] - floor[idx]))[: 100 - sum(floor)]:
        floor[i] += 1
    return floor


def _max_shift_pp(a: list[float], b: list[float]) -> float:
    return round(100.0 * max((abs(x - y) for x, y in zip(a, b)), default=0.0), 1)


def _norm_issue_key(issue: dict) -> str:
    raw = str(issue.get("key") or issue.get("id") or issue.get("title") or "").strip().lower()
    return re.sub(r"\s+", " ", raw)


def compare_issues(
    no_persona_issues: list[dict] | None = None,
    manual_issues: list[dict] | None = None,
    synthetic_issues: list[dict] | None = None,
) -> dict:
    """Compare actionable, text-verified problems found across (a), (b), and (c).

    Each issue item may contain:
      - `id` or `key` or `title`: identifier used to detect duplicates across arms
      - `title`: human-readable issue title
      - `actionable`: bool (default True) — whether this is something we can actually fix in the policy/notice
      - `verified_against_text`: bool (default True) — whether a human confirmed it matches the official text
    """
    a_list = list(no_persona_issues or [])
    b_list = list(manual_issues or [])
    c_list = list(synthetic_issues or [])

    baseline_keys = {_norm_issue_key(x) for x in a_list + b_list if _norm_issue_key(x)}
    manual_keys = {_norm_issue_key(x) for x in b_list if _norm_issue_key(x)}
    seen_c: set[str] = set()

    new_actionable: list[dict] = []
    overlap_with_baseline: list[dict] = []
    unverified_or_non_actionable: list[dict] = []

    for item in c_list:
        key = _norm_issue_key(item)
        if not key or key in seen_c:
            continue
        seen_c.add(key)
        actionable = bool(item.get("actionable", True))
        verified = bool(item.get("verified_against_text", True))
        if key in baseline_keys:
            overlap_with_baseline.append(item)
        elif actionable and verified:
            new_actionable.append(item)
        else:
            unverified_or_non_actionable.append(item)

    c_keys = seen_c
    overlap_manual = len(c_keys & manual_keys)
    overlap_rate = round(overlap_manual / len(c_keys), 3) if c_keys else None

    return {
        "provided": bool(a_list or b_list or c_list),
        "no_persona_count": len({_norm_issue_key(x) for x in a_list if _norm_issue_key(x)}),
        "manual_count": len(manual_keys),
        "synthetic_total_unique": len(c_keys),
        "overlap_with_baseline_count": len(overlap_with_baseline),
        "overlap_with_manual_rate": overlap_rate,
        "new_actionable_count": len(new_actionable),
        "unverified_or_non_actionable_count": len(unverified_or_non_actionable),
        "new_actionable_issues": [
            {"id": x.get("id") or _norm_issue_key(x), "title": x.get("title") or x.get("id") or ""}
            for x in new_actionable
        ],
    }


def evaluate_expansion_decision(
    *,
    is_mock: bool,
    persona_lift_vs_no_persona_pp: float,
    persona_lift_vs_manual_pp: float,
    noise_floor_pp: float,
    issue_comparison: dict,
    diagnostic_warnings: list[dict],
) -> dict:
    """Apply the '새로 고칠 문제가 늘었을 때만 확대' rule (grok.md #5, gemini.md #5)."""
    lift_clears_noise = persona_lift_vs_no_persona_pp > noise_floor_pp
    differs_from_manual = persona_lift_vs_manual_pp > noise_floor_pp
    issues_provided = bool(issue_comparison.get("provided"))
    new_actionable_n = int(issue_comparison.get("new_actionable_count", 0))
    has_diag_warnings = len(diagnostic_warnings) > 0

    checklist = [
        {
            "criterion": "1. 모의(mock)가 아닌 실제 모델 실행 + 사람 검토",
            "result": "미충족(모의 시험)" if is_mock else "실제 모델 실행",
            "passed": not is_mock,
        },
        {
            "criterion": f"2. 인물 없음 대비 순효과가 흔들림 폭({noise_floor_pp:.1f}%p) 초과",
            "result": f"{persona_lift_vs_no_persona_pp:.1f}%p (기준 {noise_floor_pp:.1f}%p)",
            "passed": lift_clears_noise,
        },
        {
            "criterion": "3. 수작업 소수 조건 대비 새로 고칠 문제(문안 대조 확인)가 1건 이상 증가",
            "result": (
                f"신규 수정 가능 문제 {new_actionable_n}건"
                if issues_provided
                else "미입력(쟁점·막힘 대조 필요)"
            ),
            "passed": issues_provided and new_actionable_n > 0,
        },
        {
            "criterion": "4. 응답 쏠림·학력/소득 과대추정 자동 진단 경고 확인",
            "result": f"경고 {len(diagnostic_warnings)}건 — 현장·생활여건 재확인 필요" if has_diag_warnings else "특이 경고 없음",
            "passed": not has_diag_warnings,
        },
    ]

    reasons: list[str] = []
    if is_mock:
        status = "pending_human_review"
        label = "판단 보류(모의 시험 결과 — 확대 근거로 쓸 수 없음)"
        reasons.append("모의(mock) 응답은 자리 채움 값이므로 확대·축소 판단 근거로 사용할 수 없습니다.")
    elif not lift_clears_noise:
        status = "do_not_expand"
        label = "확대 중단(인물 없음·수작업 유지)"
        reasons.append(
            f"합성 인물을 넣어도 인물 없는 대조군과 최대 차이({persona_lift_vs_no_persona_pp:.1f}%p)가 "
            f"흔들림 폭({noise_floor_pp:.1f}%p) 이하입니다."
        )
    elif issues_provided and new_actionable_n == 0:
        status = "do_not_expand"
        label = "확대 중단(수작업 소수 조건 유지)"
        reasons.append(
            "수작업 소수 조건과 비교했을 때 문안과 맞고 새로 고칠 수 있는 문제가 늘지 않았습니다."
        )
    elif not issues_provided:
        status = "hold"
        label = "보류(사람 검토로 신규 수정 문제 확인 후 결정)"
        reasons.append(
            "응답 분포 차이는 보이나, 수작업 조건 대비 새로 고칠 문제가 늘었는지 확인 기록이 아직 없습니다."
        )
        if not differs_from_manual:
            reasons.append(
                f"수작업 소수 조건과의 분포 차이({persona_lift_vs_manual_pp:.1f}%p)도 흔들림 폭({noise_floor_pp:.1f}%p) 이내입니다."
            )
    elif has_diag_warnings:
        status = "hold"
        label = "조건부 보류(자동 진단 경고 확인 후 제한적 확대)"
        reasons.append(
            f"신규 수정 가능 문제 {new_actionable_n}건이 늘었으나, 자동 진단 경고 {len(diagnostic_warnings)}건이 있어 "
            "고정관념 격차·응답 쏠림 여부를 먼저 확인하시기 바랍니다."
        )
    else:
        status = "expand"
        label = "확대 검토 가능(신규 수정 가능 문제 증가 확인)"
        reasons.append(
            f"인물 순효과({persona_lift_vs_no_persona_pp:.1f}%p)가 흔들림 폭({noise_floor_pp:.1f}%p)을 넘고, "
            f"수작업 조건 대비 문안과 맞는 신규 수정 가능 문제가 {new_actionable_n}건 늘었습니다."
        )

    return {
        "rule": "새로 고칠 문제가 늘었을 때만 확대",
        "status": status,
        "label": label,
        "lift_clears_noise": lift_clears_noise,
        "differs_from_manual": differs_from_manual,
        "new_actionable_count": new_actionable_n,
        "reasons": reasons,
        "checklist": checklist,
    }


def _call_eval(evaluate: Callable, state: dict, questions: dict, keys: list[str]) -> tuple[list[float], str, int]:
    out = evaluate(state, questions, label="persona_contrast", cache=False, retries=0)
    probs = _normalize_probs(out["answers"]["q"]["probabilities"], keys)
    model = str(out.get("model") or "")
    tokens = int((out.get("usage") or {}).get("input_tokens") or 0)
    return probs, model, tokens


def run_contrast(
    spec: dict,
    synthetic_people: list[dict],
    *,
    manual_conditions: list[dict] | None = None,
    evaluate: Callable | None = None,
    no_persona_issues: list[dict] | None = None,
    manual_issues: list[dict] | None = None,
    synthetic_issues: list[dict] | None = None,
    context: dict[str, dict] | None = None,
    include_reversed: bool = True,
    review_minutes: dict[str, int] | None = None,
    limits: budget.Limits | None = None,
    budget_path: Path | None = None,
) -> dict:
    """Execute the 3-arm comparison (a) no persona, (b) manual conditions, (c) synthetic personas.

    Parameters
    ----------
    spec: dict with `title`, `policy_text`, `question`, `options`
    synthetic_people: list of persona dicts (`uuid`, `profile`, plus optional demographic fields)
    manual_conditions: list of hand-written condition dicts (`id`, `label`, `profile`); defaults to starter set
    evaluate: callable matching `pp.jev.evaluate` signature; defaults to `pp.jev.evaluate`
    """
    if budget.current() is None:
        ledger = budget.Budget(limits or budget.Limits(), budget_path)
        with ledger.scope():
            return run_contrast(
                spec, synthetic_people, manual_conditions=manual_conditions, evaluate=evaluate,
                no_persona_issues=no_persona_issues, manual_issues=manual_issues,
                synthetic_issues=synthetic_issues, context=context, include_reversed=include_reversed,
                review_minutes=review_minutes,
            )
    options = [o.strip() for o in spec["options"] if o and o.strip()]
    if len(options) < 2:
        raise ValueError("options must contain at least 2 items")
    if not synthetic_people:
        raise ValueError("synthetic_people must not be empty")

    manual = list(manual_conditions) if manual_conditions is not None else list(DEFAULT_MANUAL_CONDITIONS)
    if not manual:
        raise ValueError("manual_conditions must not be empty")

    eval_fn = evaluate or jev.evaluate
    keys = _option_keys(options)
    k = len(options)
    policy_block = {"title": spec["title"], "text": spec["policy_text"].strip()}

    q_no_persona_main = _questions_payload(options, reverse=False, no_persona=True)
    q_no_persona_rev = _questions_payload(options, reverse=True, no_persona=True)
    q_main = _questions_payload(options, reverse=False, no_persona=False)
    q_rev = _questions_payload(options, reverse=True, no_persona=False)

    models_seen: set[str] = set()
    calls = {"no_persona": 0, "manual": 0, "synthetic": 0}
    tokens = {"no_persona": 0, "manual": 0, "synthetic": 0}

    # (a) No persona (Vanilla baseline)
    no_persona_state = {"policy": policy_block, "question": spec["question"]}
    np_main, m, t = _call_eval(eval_fn, no_persona_state, q_no_persona_main, keys)
    if m:
        models_seen.add(m)
    calls["no_persona"] += 1
    tokens["no_persona"] += t
    np_rev = np_main
    if include_reversed:
        np_rev, m, t = _call_eval(eval_fn, no_persona_state, q_no_persona_rev, keys)
        if m:
            models_seen.add(m)
        calls["no_persona"] += 1
        tokens["no_persona"] += t
    np_rev_shift = _max_shift_pp(np_main, np_rev)

    # (b) Manual small conditions
    manual_rows: list[dict] = []
    manual_main_probs: list[list[float]] = []
    manual_rev_probs: list[list[float]] = []
    for cond in manual:
        st = {"policy": policy_block, "question": spec["question"], "person": cond["profile"]}
        p_main, m, t = _call_eval(eval_fn, st, q_main, keys)
        if m:
            models_seen.add(m)
        calls["manual"] += 1
        tokens["manual"] += t
        p_rev = p_main
        if include_reversed:
            p_rev, m, t = _call_eval(eval_fn, st, q_rev, keys)
            if m:
                models_seen.add(m)
            calls["manual"] += 1
            tokens["manual"] += t
        manual_main_probs.append(p_main)
        manual_rev_probs.append(p_rev)
        manual_rows.append(
            {
                "id": cond.get("id") or cond.get("label"),
                "label": cond.get("label") or cond.get("id"),
                "percent": _int_percent(p_main),
                "top_option": options[max(range(k), key=lambda i: p_main[i])],
            }
        )
    manual_mean = _mean_shares(manual_main_probs, k)
    manual_rev_shift = _max_shift_pp(manual_mean, _mean_shares(manual_rev_probs, k))

    # (c) Synthetic personas
    synth_main_map: dict[str, list[float]] = {}
    synth_rev_map: dict[str, list[float]] = {}
    for p in synthetic_people:
        st = {"policy": policy_block, "question": spec["question"], "person": p["profile"]}
        p_main, m, t = _call_eval(eval_fn, st, q_main, keys)
        if m:
            models_seen.add(m)
        calls["synthetic"] += 1
        tokens["synthetic"] += t
        synth_main_map[p["uuid"]] = p_main
        if include_reversed:
            p_rev, m, t = _call_eval(eval_fn, st, q_rev, keys)
            if m:
                models_seen.add(m)
            calls["synthetic"] += 1
            tokens["synthetic"] += t
            synth_rev_map[p["uuid"]] = p_rev
        else:
            synth_rev_map[p["uuid"]] = p_main

    synth_mean = _mean_shares(list(synth_main_map.values()), k)
    synth_rev_shift = _max_shift_pp(synth_mean, _mean_shares(list(synth_rev_map.values()), k))

    # Net-effect lifts
    lift_vs_no_persona = _max_shift_pp(synth_mean, np_main)
    lift_vs_manual = _max_shift_pp(synth_mean, manual_mean)
    manual_vs_no_persona = _max_shift_pp(manual_mean, np_main)
    noise_floor = round(max(NOISE_FLOOR_PP, synth_rev_shift, np_rev_shift), 1)

    # Diagnostics (item 2: dispersion compression, edu/income overestimation, question reliability)
    diag = diagnostics.diagnose_survey(spec, synthetic_people, synth_main_map, context=context)
    if lift_vs_no_persona <= noise_floor:
        diag["warnings"].append(
            {
                "code": "low_persona_net_effect",
                "level": "warn",
                "message": (
                    f"합성 인물을 넣어도 인물 없는 대조군과 최대 차이({lift_vs_no_persona:.1f}%p)가 "
                    f"흔들림 폭({noise_floor:.1f}%p) 이하입니다. 뻔한 문항이거나 모델 기본 상식이 우세할 수 있습니다."
                ),
                "hint": "인물 규모를 늘리기 전에 문항을 구체화하거나 수작업 조건만으로 충분한지 검토하세요.",
            }
        )

    issue_cmp = compare_issues(no_persona_issues, manual_issues, synthetic_issues)

    is_mock = (
        (evaluate is None and jev.provider() == "mock")
        or (bool(models_seen) and all(m == "mock" for m in models_seen))
    )
    decision = evaluate_expansion_decision(
        is_mock=is_mock,
        persona_lift_vs_no_persona_pp=lift_vs_no_persona,
        persona_lift_vs_manual_pp=lift_vs_manual,
        noise_floor_pp=noise_floor,
        issue_comparison=issue_cmp,
        diagnostic_warnings=diag["warnings"],
    )

    rev_mins = review_minutes or {}

    def _arm_summary(
        key: str,
        label: str,
        n_units: int,
        mean: list[float],
        rev_shift: float,
        vs_np: float | None,
        vs_manual: float | None,
        issue_n: int | None,
    ) -> dict:
        top_idx = max(range(k), key=lambda i: mean[i])
        return {
            "arm": key,
            "label": label,
            "n": n_units,
            "calls": calls[key],
            "input_tokens": tokens[key],
            "percent": _int_percent(mean),
            "shares": [round(x, 4) for x in mean],
            "top_option": options[top_idx],
            "top_percent": _int_percent(mean)[top_idx],
            "reversal_shift_pp": rev_shift,
            "diff_vs_no_persona_pp": vs_np,
            "diff_vs_manual_pp": vs_manual,
            "unique_issues": issue_n,
            "review_minutes": rev_mins.get(key),
        }

    arms = {
        "no_persona": _arm_summary(
            "no_persona", "(a) 인물 없음", 1, np_main, np_rev_shift, 0.0, manual_vs_no_persona,
            issue_cmp["no_persona_count"] if issue_cmp["provided"] else None,
        ),
        "manual": _arm_summary(
            "manual", "(b) 수작업 소수 조건", len(manual), manual_mean, manual_rev_shift,
            manual_vs_no_persona, 0.0,
            issue_cmp["manual_count"] if issue_cmp["provided"] else None,
        ),
        "synthetic": _arm_summary(
            "synthetic", "(c) 합성 인물", len(synthetic_people), synth_mean, synth_rev_shift,
            lift_vs_no_persona, lift_vs_manual,
            issue_cmp["synthetic_total_unique"] if issue_cmp["provided"] else None,
        ),
    }

    return {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "mock" if is_mock else "model",
        "models": sorted(models_seen),
        "policy_title": spec["title"],
        "question": spec["question"],
        "options": options,
        "arms": arms,
        "manual_details": manual_rows,
        "net_effect": {
            "persona_lift_vs_no_persona_pp": lift_vs_no_persona,
            "persona_lift_vs_manual_pp": lift_vs_manual,
            "manual_lift_vs_no_persona_pp": manual_vs_no_persona,
            "noise_floor_pp": noise_floor,
            "clears_noise": lift_vs_no_persona > noise_floor,
        },
        "issue_comparison": issue_cmp,
        "diagnostics": diag,
        "expansion_decision": decision,
        "budget": budget.current().snapshot(),
    }


def render_markdown_report(report: dict) -> str:
    """Render the 3-arm comparison report, diagnostics warnings, and expansion judgment box as Markdown."""
    opts = report["options"]
    arms = report["arms"]
    net = report["net_effect"]
    issues = report["issue_comparison"]
    dec = report["expansion_decision"]
    diag = report["diagnostics"]

    def _dist_str(pcts: list[int]) -> str:
        return " / ".join(f"{o} {p}%" for o, p in zip(opts, pcts))

    def _fmt_opt(val, suffix: str = "") -> str:
        return "-" if val is None else f"{val}{suffix}"

    lines = [
        f"# 인물 순효과 대조 보고서 — {report['policy_title']}",
        "",
        f"- **실행 방식**: {'모의 시험(mock, 자리 채움 값 — 해석·확대 근거 사용 금지)' if report['mode'] == 'mock' else '모델 실행 (' + ', '.join(report['models']) + ')'}",
        f"- **문항**: {report['question']}",
        f"- **선택지**: {', '.join(opts)}",
        f"- **생성 시각(UTC)**: {report['created_at']}",
        "",
        "## 1. 세 조건 대조 표",
        "",
        "| 비교 조건 | 대상 수 | 호출 수 | 1순위 선택지 | 응답 분포(%) | 인물 없음 대비 차 | 수작업 대비 차 | 순서 흔들림 | 확인된 문제 수 | 검토 시간(분) |",
        "|---|---:|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for key in ("no_persona", "manual", "synthetic"):
        a = arms[key]
        lines.append(
            f"| {a['label']} | {a['n']:,} | {a['calls']:,} | {a['top_option']} ({a['top_percent']}%) | "
            f"{_dist_str(a['percent'])} | {_fmt_opt(a['diff_vs_no_persona_pp'], '%p')} | "
            f"{_fmt_opt(a['diff_vs_manual_pp'], '%p')} | {a['reversal_shift_pp']:.1f}%p | "
            f"{_fmt_opt(a['unique_issues'], '건')} | {_fmt_opt(a['review_minutes'])} |"
        )

    lines += [
        "",
        "### 순효과 요약",
        f"- **인물 순효과 (합성 인물 − 인물 없음)**: `{net['persona_lift_vs_no_persona_pp']:.1f}%p` (흔들림 기준 `{net['noise_floor_pp']:.1f}%p` → {'기준 초과' if net['clears_noise'] else '기준 이하'})",
        f"- **수작업 대비 변화 (합성 인물 − 수작업 소수 조건)**: `{net['persona_lift_vs_manual_pp']:.1f}%p`",
        f"- **수작업 자체 효과 (수작업 소수 조건 − 인물 없음)**: `{net['manual_lift_vs_no_persona_pp']:.1f}%p`",
    ]
    if issues["provided"]:
        lines.append(
            f"- **문제 발견 비교**: 수작업 `{issues['manual_count']}건` vs 합성 `{issues['synthetic_total_unique']}건` "
            f"(기존과 겹침 `{issues['overlap_with_baseline_count']}건`, **문안 확인 신규 수정 가능 문제 `{issues['new_actionable_count']}건`**)"
        )
        if issues["new_actionable_issues"]:
            names = ", ".join(x["title"] for x in issues["new_actionable_issues"])
            lines.append(f"- **합성에서 새로 찾은 수정 가능 문제**: {names}")

    lines += [
        "",
        "## 2. 자동 진단 경고(응답 쏠림 · 학력/소득 과대추정 · 문항 신뢰도)",
        "",
        diagnostics.format_warnings_markdown(diag),
        "",
        "## 3. '새로 고칠 문제가 늘었을 때만 확대' 판단 칸",
        "",
        f"> **자동 판정**: **{dec['label']}** (`{dec['status']}`)",
        "",
        "| 점검 기준 | 측정 결과 | 충족 여부 |",
        "|---|---|---|",
    ]
    for row in dec["checklist"]:
        mark = "충족" if row["passed"] else "미충족"
        lines.append(f"| {row['criterion']} | {row['result']} | {mark} |")

    lines += ["", "**판정 사유**"]
    for reason in dec["reasons"]:
        lines.append(f"- {reason}")

    lines += [
        "",
        "| 담당자 최종 판단 칸 | 선택(체크) | 판단 메모(고칠 문제·검토 시간 기준) |",
        "|---|---|---|",
        "| `[ ]` 확대 검토 / `[ ]` 현 규모 유지 / `[ ]` 수작업만 사용 | | |",
        "",
    ]
    return "\n".join(lines)


def load_manual_conditions(path) -> list[dict]:
    """Load hand-written conditions from a JSON file (list of {id, label, profile})."""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("conditions") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("manual conditions file must contain a non-empty list")
    out = []
    for i, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("profile") or "").strip():
            raise ValueError(f"manual condition #{i} missing non-empty 'profile'")
        out.append(
            {
                "id": str(item.get("id") or f"manual-{i}"),
                "label": str(item.get("label") or f"조건 {i}"),
                "profile": str(item["profile"]).strip(),
            }
        )
    return out


def make_demo_synthetic_people(n: int = 40) -> list[dict]:
    """Build a small deterministic synthetic sample for offline mock tests when no 20k panel file exists."""
    provinces = ["서울", "경기", "부산", "대구", "전라남", "강원", "충청남", "제주"]
    bands = ["19–29세", "30대", "40대", "50대", "60대", "70세 이상"]
    edus = ["중학교", "고등학교", "4년제 대학교", "대학원"]
    incomes = ["lt10", "mid", "ge100"]
    people = []
    for i in range(n):
        age_band = bands[i % len(bands)]
        age = {"19–29세": 24, "30대": 35, "40대": 45, "50대": 55, "60대": 65, "70세 이상": 74}[age_band]
        slot = i // len(bands)
        sex = "여자" if slot % 2 else "남자"
        prov = provinces[(slot + i % len(bands)) % len(provinces)]
        edu = edus[slot % len(edus)]
        inc = incomes[slot % len(incomes)]
        people.append(
            {
                "uuid": f"demo-{i + 1:04d}",
                "sex": sex,
                "age": age,
                "age_band": age_band,
                "province": prov,
                "capital": prov in ("서울", "경기"),
                "education_level": edu,
                "income": inc,
                "profile": (
                    f"성별·나이: {sex}, {age}세 / 사는 곳: {prov}-중구 / 학력: {edu}\n\n"
                    f"{prov}에 사는 {age}세 합성 인물 예시입니다."
                ),
            }
        )
    return people


if __name__ == "__main__":
    # Safe mock demo when invoked directly via `python -m pp.persona_contrast`
    os.environ.setdefault("PP_JEV_PROVIDER", "mock")
    sample_spec = {
        "title": "모의 시험 예시 정책",
        "policy_text": "만 70세 이상 시민에게 대중교통 요금을 지원합니다.",
        "question": "만 70세 이상 대중교통 요금 지원에 찬성하십니까?",
        "options": ["찬성", "반대", "잘 모르겠다"],
    }
    rep = run_contrast(sample_spec, make_demo_synthetic_people(24))
    print(render_markdown_report(rep))
