"""From per-person option probabilities to the result screen: shares, control and order effects, group splits.

Shares are means of each person's normalized probabilities (not argmax counts). Group differences are only
reported when they clear a threshold that includes the sampling width a real survey of this size would have
(Bonferroni z for 17 pairs), the control-sentence and option-order shifts of the two groups, and 3 points.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

from ppservice.persona_accuracy import unavailable_accuracy
from ppservice import historical_baseline

Z_MULTI = 2.97          # two-sided 0.05 over 17 pairwise comparisons (Bonferroni)
MIN_GROUP = 100
UNSTABLE_PP = 7.0
FLOOR_PP = 3.0
AXES = [("연령대", "age_band", ["19–29세", "30대", "40대", "50대", "60대", "70세 이상"]),
        ("성별", "sex", ["남자", "여자"]),
        ("지역", "region", ["수도권", "비수도권"])]
BASELINE = Path(__file__).resolve().parents[1] / "data" / "baseline.json"
UNSURE = re.compile(r"모르|판단하기 어렵|유보|무응답")
# Add-ons whose values are bands or flags drawn from statistics: never a person's amount, eligibility or ability to
# repay.
MONEY_ADDONS = {"finance", "assets", "welfare"}
MONEY_LIMIT = ("소득·자산 구간과 수급 표시는 통계로 배정한 가정이라 지원 금액·수급 자격·상환 능력을 계산하거나 판정하는 데 "
               "쓰지 않습니다.")
DIGITAL_LIMIT = ("디지털 항목은 ‘인터넷·스마트폰으로 필요한 정보를 찾을 수 있는지’ 설문의 대리값이며, 서류 제출·앱 신청 같은 "
                 "절차를 해낼 수 있는지를 뜻하지 않습니다.")


def mean_shares(rows: list[list[float]], k: int) -> list[float]:
    if not rows:
        return [0.0] * k
    return [sum(r[i] for r in rows) / len(rows) for i in range(k)]


def int_percent(shares: list[float]) -> list[int]:
    """Whole percentages that add up to 100 (largest remainder)."""
    total = sum(shares) or 1.0
    exact = [100 * s / total for s in shares]
    floor = [int(x) for x in exact]
    for i in sorted(range(len(exact)), key=lambda i: -(exact[i] - floor[i]))[: 100 - sum(floor)]:
        floor[i] += 1
    return floor


def max_shift_pp(a: list[float], b: list[float]) -> float:
    return round(100 * max((abs(x - y) for x, y in zip(a, b)), default=0.0), 1)


def region(person: dict) -> str:
    return "수도권" if person.get("capital") else "비수도권"


def load_baseline(path: Path = BASELINE) -> dict | None:
    # Historical baseline.json remains on disk, but is not a version-matched baseline.
    return None


def summarize(spec: dict, people: list[dict], answers: dict[str, dict[str, list[float]]], lint: list[dict],
              baseline: dict | None = None, *, panel_version: str | None = None,
              model_version: str | None = None, future: dict | None = None,
              include_diagnostics: bool = False, context: dict | None = None) -> dict:
    options = spec["options"]
    k = len(options)
    by_uuid = {p["uuid"]: {**p, "region": region(p)} for p in people}
    main, placebo, rev = answers.get("main", {}), answers.get("placebo", {}), answers.get("reversed", {})
    main_shares = mean_shares(list(main.values()), k)
    top = max(range(k), key=lambda i: main_shares[i])
    paired_p = [u for u in main if u in placebo]
    paired_r = [u for u in main if u in rev]
    placebo_shift = max_shift_pp(mean_shares([main[u] for u in paired_p], k), mean_shares([placebo[u] for u in paired_p], k))
    reversal_shift = max_shift_pp(mean_shares([main[u] for u in paired_r], k), mean_shares([rev[u] for u in paired_r], k))

    def group_stats(attr: str, value: str) -> dict:
        ids = [u for u in main if by_uuid.get(u, {}).get(attr) == value]
        g = group_top(ids, main, placebo, rev, k, top)
        return {"group": value, "ids": ids, **g,
                "percent": int_percent(mean_shares([main[u] for u in ids], k)) if ids else None}

    axes, splits = [], []
    for label, attr, values in AXES:
        rows = [g for g in (group_stats(attr, v) for v in values) if g["n"] > 0]
        usable = [g for g in rows if g["n"] >= MIN_GROUP]
        axis = {"axis": label, "groups": [{"group": g["group"], "n": g["n"], "percent": g["percent"],
                                           "top_percent": round(100 * g["top_share"])} for g in rows]}
        if len(usable) >= 2:
            hi = max(usable, key=lambda g: g["top_share"])
            lo = min(usable, key=lambda g: g["top_share"])
            c = compare_groups(hi["ids"], lo["ids"], main, placebo, rev, k, top)
            diff, threshold = c["diff"], c["threshold"]
            axis.update(high=hi["group"], low=lo["group"], diff_pp=round(diff, 1), threshold_pp=round(threshold, 1),
                        distinguishable=diff > threshold,
                        parts={name: round(v, 1) for name, v in c["parts"].items()})
            if diff > threshold:
                splits.append({"axis": label, "high": hi["group"], "low": lo["group"], "diff_pp": round(diff)})
        axes.append(axis)
    splits.sort(key=lambda s: -s["diff_pp"])

    warnings = [f for f in lint if f["level"] == "warn"]
    unstable = reversal_shift > UNSTABLE_PP
    if warnings or unstable:
        next_action = {"kind": "fix_question", "text": "문항을 고쳐 다시 돌려 보세요." if warnings
                       else "선택지 순서만 바꿔도 결과가 흔들립니다. 문항과 선택지를 다듬어 다시 돌려 보세요."}
    elif splits:
        s = splits[0]
        next_action = {"kind": "ask_groups", "text": f"‘{s['high']}’, ‘{s['low']}’ 집단에 실제로 먼저 물어보세요."}
    else:
        next_action = {"kind": "real_survey", "text": "집단 간 차이가 뚜렷하지 않습니다. 실제 조사로 확인하세요."}

    percent = int_percent(main_shares)
    cautions = []
    unsure = [i for i, o in enumerate(options) if UNSURE.search(o)]
    if unsure:
        cautions.append("유보 선택지의 모의 응답 비율은 실제 여론의 유보율이 아닙니다. 이 실행판의 유보 편향은 검증 전입니다.")
    accuracy = unavailable_accuracy()
    historical = historical_baseline.load() if panel_version else None
    if historical and historical['panel_version'] == panel_version:
        accuracy['payload'].update(historical_baseline=historical, scope=historical['scope'],
            reasons=['model_unverified', 'enrichment_not_applied'])
        if model_version != historical['inputs']['model']['model_revision']:
            accuracy['payload']['reasons'].append('historical_model_mismatch')
        if unsure:
            values = historical['unsure_signed_pp']
            measured = ', '.join(f'{v:+.1f}%p' for v in values)
            cautions = [f'과거 진단의 결혼·재혼 문항에서 유보 선택지 차이(합성−실측)는 각각 {measured}였습니다. '
                        '현재 문항의 유보 편향 추정치가 아닙니다.'] if values else cautions
    addons = addons_view(panel_version)
    if addons:
        names = {a["name"] for a in addons}
        cautions.append(f"생활 여건 애드온 {len(addons)}종({', '.join(a['title'] for a in addons)})을 붙인 패널입니다. "
                        "공공통계에서 뽑은 가정이며 개인의 실제 정보가 아닙니다."
                        + (" 소득·자산 정보가 붙으면 소득에 따른 응답 차이가 실측보다 크게 나올 수 있습니다."
                           if names & {"finance", "assets"} else "")
                        + (" " + MONEY_LIMIT if names & MONEY_ADDONS else "")
                        + (" " + DIGITAL_LIMIT if "digital" in names else ""))
    future_result = future_view(people, answers, k, top, future, max(placebo_shift, reversal_shift)) if future else None
    if future_result:
        cautions.append(f"‘5년 뒤 보기’는 같은 합성 인물 {future_result['n']:,}명을 {future_result['year']}년의 상태"
                        "(나이·일·사는 곳·혼인·개인 소득 금액)로 굴려 다시 물은 것입니다. 공공통계의 연간 변화 확률로 굴린"
                        " 가정이며 예측이 아닙니다. 그사이 성인이 되는 사람은 없고 사망자는 뺐습니다.")
    summary_text = (f"합성 인물 {len(main):,}명 모의 응답(AI 추정, 실제 여론조사 아님)에서 ‘{options[top]}’ {percent[top]}%."
                    " 실측 비교 검증 전이며 실제 조사로 확인이 필요합니다.")
    if historical and historical['panel_version'] == panel_version:
        summary_text = (f"합성 인물 {len(main):,}명 모의 응답(AI 추정, 실제 여론조사 아님)에서 ‘{options[top]}’ {percent[top]}%. "
                        f"과거 진단 5문항(2024 사회조사)의 비교 문항 평균 절대 차이 {historical['mae_pp']}%p이며 "
                        "이 문항의 오차 범위가 아닙니다. 현재 실행과 진단 모델판의 동일성은 미확인입니다.")
    out = {
        "n": len(main), "options": options, "percent": percent, "top": top,
        "placebo_shift_pp": placebo_shift, "reversal_shift_pp": reversal_shift, "unstable": unstable,
        "splits": splits, "axes": axes, "baseline": None, "accuracy": accuracy, "next_action": next_action,
        "lint_warnings": len(warnings), "summary_text": summary_text, "cautions": cautions, "addons": addons,
        "future": future_result,
        "attribution": result_attribution(panel_version, [a["name"] for a in addons],
                                          ["통계청 「2024 사회조사」(과거 진단 비교 기준)"]
                                          if historical and historical['panel_version'] == panel_version else []),
    }
    no_persona = answers.get("no_persona")
    if no_persona:
        np_shares = mean_shares(list(no_persona.values()), k)
        lift_pp = max_shift_pp(main_shares, np_shares)
        noise_pp = round(max(FLOOR_PP, placebo_shift, reversal_shift), 1)
        clears = lift_pp > noise_pp
        out["persona_net_effect"] = {
            "no_persona_percent": int_percent(np_shares),
            "persona_lift_pp": lift_pp,
            "noise_floor_pp": noise_pp,
            "clears_noise": clears,
        }
        if not clears:
            cautions.append(
                f"인물 설정을 넣어도 인물 없는 대조군과 최대 차이({lift_pp:.1f}%p)가 흔들림 폭({noise_pp:.1f}%p) 이하입니다. "
                "뻔한 문항이거나 모델 기본 상식이 우세할 수 있습니다."
            )
    if include_diagnostics:
        from pp import diagnostics as pp_diag

        diag = pp_diag.diagnose_survey(spec, people, main, context=context)
        out["diagnostics"] = diag
        for item in (*diag["reliability_findings"], *diag["warnings"]):
            if item["message"] not in cautions:
                cautions.append(item["message"])
    return out


def result_attribution(panel_version: str | None, addons: list[str], extra_stats: list[str] = ()) -> dict:
    """Source and terms of a service result: the 20k panel's recorded (or verified) revision, the add-ons' tables."""
    from pp import attribution

    from . import panel

    meta = {**attribution.recorded(panel.BUNDLE), "panel_version": panel_version}
    changes = attribution.DEFAULT_CHANGES + (("addons",) if addons else ())
    return attribution.build(meta, changes=changes, stats=[*attribution.addon_statistics(addons), *extra_stats])


def group_top(ids: list[str], main: dict, placebo: dict, rev: dict, k: int, top: int) -> dict:
    """A group's top-option share in the main arm and in the two control arms (members present in each arm)."""
    return {"n": len(ids), "top_share": mean_shares([main[u] for u in ids if u in main], k)[top],
            "placebo_top": mean_shares([placebo[u] for u in ids if u in placebo], k)[top],
            "reversed_top": mean_shares([rev[u] for u in ids if u in rev], k)[top]}


def compare_tops(a: dict, b: dict, z: float = Z_MULTI) -> dict:
    """compare_groups() on two group_top() results; `z` widens the sampling width when many groups are compared."""
    p1, p2 = a["top_share"], b["top_share"]
    width = 100 * z * math.sqrt(p1 * (1 - p1) / max(1, a["n"]) + p2 * (1 - p2) / max(1, b["n"]))
    placebo_dd = 100 * abs((p1 - a["placebo_top"]) - (p2 - b["placebo_top"]))
    reversal_dd = 100 * abs((p1 - a["reversed_top"]) - (p2 - b["reversed_top"]))
    return {"diff": 100 * (p1 - p2), "threshold": max(width, placebo_dd, reversal_dd, FLOOR_PP),
            "parts": {"sampling": width, "placebo": placebo_dd, "reversal": reversal_dd}, "a": a, "b": b}


def compare_groups(ids_a: list[str], ids_b: list[str], main: dict, placebo: dict, rev: dict, k: int, top: int) -> dict:
    """Two groups' top-option difference (a − b, percentage points, unrounded) and the smallest difference worth
    reading: the sampling width of two shares, the control-sentence and option-order shifts' difference between the
    groups, and the 3-point floor. Shared by the fixed axes in summarize() and by the rule view."""
    return compare_tops(group_top(ids_a, main, placebo, rev, k, top), group_top(ids_b, main, placebo, rev, k, top))


def _small(n: int) -> str:
    return f"{n:,}명이라 비교하지 않습니다"


def rule_view(people: list[dict], answers: dict, k: int, top: int, rule: dict, states: dict,
              control_pp: float, format_pp: float, top_label: str = "1순위") -> dict:
    """"대상 규칙으로 나눠 보기": apply `rule` to each member's 2025 state and
    projected 2030 state, count who it fits, and split the stored answers — main by the 2025 judgement, the
    future_base→future pair by the 2030 judgement. Computed on request, nothing is stored."""
    from pp import config
    from pp import life_history as lh

    main, placebo, rev = answers.get("main", {}), answers.get("placebo", {}), answers.get("reversed", {})
    base, fut = answers.get("future_base", {}), answers.get("future", {})
    in25, out25, und25 = [], [], 0
    in30, out30, und30, dead = [], [], 0, 0
    for p in people:
        st = states.get(p["uuid"])
        v = lh.eligible(rule, st["now"]) if st else None
        (in25 if v else out25 if v is False else []).append(p["uuid"])
        und25 += v is None
        if st is None or st["alive"] is None:  # no forecast row
            und30 += 1
            continue
        if st["alive"] is False:
            dead += 1
            continue
        v = lh.eligible(rule, st["then"])
        (in30 if v else out30 if v is False else []).append(p["uuid"])
        und30 += v is None
    total25, total30 = len(people), len(people) - dead
    y2025 = {"n": len(in25), "pct": round(100 * len(in25) / max(1, total25)), "undetermined": und25, "total": total25}
    y2030 = {"n": len(in30), "pct": round(100 * len(in30) / max(1, total30)), "undetermined": und30, "total": total30}

    a, b = [u for u in in25 if u in main], [u for u in out25 if u in main]
    main_split, main_small = None, None
    if len(a) >= MIN_GROUP and len(b) >= MIN_GROUP:
        c = compare_groups(a, b, main, placebo, rev, k, top)
        main_split = {"in": {"n": len(a), "top": round(100 * c["a"]["top_share"])},
                      "out": {"n": len(b), "top": round(100 * c["b"]["top_share"])},
                      "diff_pp": round(c["diff"], 1), "threshold_pp": round(c["threshold"], 1),
                      "parts": {name: round(v, 1) for name, v in c["parts"].items()},
                      "distinguishable": abs(c["diff"]) > c["threshold"]}
    else:
        main_small = _small(min(len(a), len(b)))

    def shift_group(ids: list[str]) -> tuple[dict | None, str | None]:
        pairs = [u for u in ids if u in base and u in fut]
        if len(pairs) < MIN_GROUP:
            return None, _small(len(pairs))
        now_s, fut_s = mean_shares([base[u] for u in pairs], k)[top], mean_shares([fut[u] for u in pairs], k)[top]
        diffs = [fut[u][top] - base[u][top] for u in pairs]
        mean = sum(diffs) / len(diffs)
        sd = math.sqrt(sum((d - mean) ** 2 for d in diffs) / len(diffs))
        sampling = 100 * Z_MULTI * sd / math.sqrt(len(pairs))
        threshold = max(FLOOR_PP, control_pp, format_pp, sampling)
        shift = 100 * (fut_s - now_s)
        return {"n": len(pairs), "now_top": round(100 * now_s), "future_top": round(100 * fut_s), "shift_pp": round(shift, 1),
                "threshold_pp": round(threshold, 1), "sampling_pp": round(sampling, 1),
                "distinguishable": abs(shift) > threshold}, None

    g_in, in_small = shift_group(in30)
    g_out, out_small = shift_group(out30)
    future_split = {"in": g_in, "in_small": in_small, "out": g_out, "out_small": out_small}
    bands: dict[str, int] = {}
    for u in in30:
        label = config.age_band(states[u]["then"]["age"])
        bands[label] = bands.get(label, 0) + 1
    age_bands = [{"group": label, "n": bands[label]} for _, _, label in config.AGE_BANDS if bands.get(label)]

    signed = lambda x: f"{x:+.1f}%p"  # noqa: E731
    line1 = (f"이 규칙에 맞는 합성 인물(실제 대상 인원 아님): 2025년 상태로 {y2025['n']:,}명({y2025['pct']}%) · "
             f"2030년 상태로 {y2030['n']:,}명({y2030['pct']}%) · 자료가 없어 판정하지 못한 수 2025년 {und25:,}명 · 2030년 {und30:,}명")
    part_in = (f"2030년 상태가 규칙에 맞는 {g_in['n']:,}명의 ‘{top_label}’(상태 블록을 붙인 답) 지금 {g_in['now_top']}% → "
               f"2030년 {g_in['future_top']}%({signed(g_in['shift_pp'])})") if g_in else f"2030년 상태가 규칙에 맞는 사람은 {in_small}"
    part_out = (f"맞지 않는 {g_out['n']:,}명 {g_out['now_top']}% → {g_out['future_top']}%({signed(g_out['shift_pp'])})") if g_out \
        else f"맞지 않는 사람은 {out_small}"
    thr = (g_in or g_out or {}).get("threshold_pp")
    line2 = f"{part_in} · {part_out}" + (f" · 이동의 믿을 수 있는 최소 차이 {thr}%p" if thr is not None else "")
    if main_split:
        line3 = (f"2025년 상태로 나눈 두 집단의 ‘{top_label}’ 차이(본 문항 답): 맞는 {main_split['in']['n']:,}명 {main_split['in']['top']}% − "
                 f"맞지 않는 {main_split['out']['n']:,}명 {main_split['out']['top']}% = {signed(main_split['diff_pp'])} · "
                 f"두 집단 차이의 믿을 수 있는 최소 차이 {main_split['threshold_pp']}%p → 최소 차이보다 "
                 + ("큼" if main_split["distinguishable"] else "작음"))
    else:
        line3 = f"2025년 상태로 나눈 두 집단 비교: {main_small}"
    text = lh.rule_text(rule)
    note = (rule.get("note") or "").strip()
    copy_text = f"입력 규칙: {text}. {line1} {line2} {line3}" + (f" 규칙에 넣지 못한 기준: {note}." if note else "")
    return {"rule": rule, "rule_text": text, "y2025": y2025, "y2030": y2030, "main_split": main_split, "main_small": main_small,
            "future_split": future_split, "age_bands_2030": age_bands, "lines": [line1, line2, line3], "copy_text": copy_text}


def future_view(people: list[dict], answers: dict, k: int, top: int, meta: dict, control_pp: float) -> dict | None:
    """The "5년 뒤 보기" block: the same people asked with their base-year state and with their projected state. The
    shift of the top option is read against the larger of the run's control effects, the format effect (how much the
    state block alone moved the base-year answers) and the 3-point floor, and split by whether a person's state
    changed at all (the research result: only people whose state changes move)."""
    base, fut, main = answers.get("future_base", {}), answers.get("future", {}), answers.get("main", {})
    pairs = [u for u in fut if u in base]
    if len(pairs) < MIN_GROUP:
        return None
    by_uuid = {p["uuid"]: p for p in people}

    def shares(d: dict, ids: list[str]) -> list[float]:
        return mean_shares([d[u] for u in ids if u in d], k)

    def shift(ids: list[str]) -> float:
        return round(100 * (shares(fut, ids)[top] - shares(base, ids)[top]), 1)

    now_p, fut_p = shares(base, pairs), shares(fut, pairs)
    format_pp = max_shift_pp(shares(main, pairs), now_p)
    changes = meta.get("changes") or {}
    changed = [u for u in pairs if changes.get(u)]
    unchanged = [u for u in pairs if not changes.get(u)]
    groups = []
    for band in AXES[0][2]:
        ids = [u for u in pairs if by_uuid.get(u, {}).get("age_band") == band]
        if len(ids) >= MIN_GROUP:
            groups.append({"group": band, "n": len(ids), "now_top": round(100 * shares(base, ids)[top]),
                           "future_top": round(100 * shares(fut, ids)[top]), "shift_pp": shift(ids)})
    threshold = max(FLOOR_PP, control_pp, format_pp)
    total = round(100 * (fut_p[top] - now_p[top]), 1)
    return {"year": meta["year"], "version": meta["version"], "n": len(pairs), "dead": meta.get("dead", 0),
            "now_percent": int_percent(now_p), "future_percent": int_percent(fut_p), "shift_pp": total,
            "format_shift_pp": format_pp, "threshold_pp": round(threshold, 1), "distinguishable": abs(total) > threshold,
            "changed_n": len(changed), "shift_changed_pp": shift(changed) if len(changed) >= MIN_GROUP else None,
            "shift_unchanged_pp": shift(unchanged) if len(unchanged) >= MIN_GROUP else None,
            "changed_kinds": {kind: sum(1 for u in changed if kind in changes[u]) for kind in ("working", "province", "marital", "income_q")},
            "age_groups": groups}


def addons_view(panel_version: str | None) -> list[dict]:
    from pp import life_context

    return [{"name": n, "title": life_context.ADDONS[n]["title"]} for n in life_context.addons_from_version(panel_version)]
