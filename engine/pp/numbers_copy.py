"""Numbers-first wording: fixed phrases, number formats and the forbidden-phrase check.

Numbers come only from engine aggregation of synthetic-person answers. Model prose still may not carry
numbers (public_rules.SYSTEM_RULES and check_output are unchanged); this module is the only place that
turns aggregates into sentences. Every phrase says whose answers these are (합성 인물), how many, and
how far the answers wobble, so that no number reads as public opinion.

Edit wording here only. tests/test_numbers_copy.py runs FORBIDDEN over every phrase this module emits
and over the good and bad examples of the numbers guideline.

Assumed engine fields (num/engine). Only ``view`` reads them, so integration edits stay in that function:

    overall:       {"n", "pool", "strata", "model", "model_kind": "judge" | "text", "favor", "oppose",
                    "unsure", "contrast_pp", "order_pp", "swing_pp", "unsure_option", "reasons_n",
                    "reasons_by_panel": {"representative", "affected"},
                    "affected": {"n", "label", "favor", "oppose", "unsure"}}
    by_group:      {"age_band" | "region" | "sex" | ...: [{"group", "n", "favor", "oppose", "unsure",
                    "exceeds"?}]}
    highlights:    [{"label", "n", "measure": "favor" | "oppose" | "unsure" | "reserve", "share",
                     "diff_pp", "issue_id"?, "groups"?, "venue"?}]
    baseline:      trend_baseline.predict(...) output plus an optional "source_name";
                   None or {"available": False} when no exact-match baseline exists
    slice_results: [{"filters": {axis: value}, "panel": "representative" | "affected", "n", "favor",
                     "oppose", "unsure", "reasons"?: [str], "reasons_n"?}]

Shares are 0..1: means of per-person probabilities (judge model) or counts / n (text-model fallback).
A row may give "reserve" (oppose + unsure) instead of oppose and unsure.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import public_rules

# Same thresholds as ppservice.survey.aggregate; a test keeps them equal.
FLOOR_PP = 3.0
UNSTABLE_PP = 7.0
MIN_GROUP = 100
TINY, SMALL = 5, 30  # under 5: counts only; under 30: counts first and a small-group badge
DEFAULT_POOL = 1_000_000
DEFAULT_STRATA = ("province", "age_band", "sex")
TABLE_AXES = ("age_band", "region", "sex")

AXIS = {"age_band": "연령대", "region": "권역", "sex": "성별", "province": "시도", "education_level": "학력",
        "income": "소득", "housing_type": "주거", "family": "가족", "occupation_major": "직업"}
STRATA = {"province": "시도", "age_band": "연령", "sex": "성별"}
INFLATED_AXES = frozenset({"education_level", "income"})
PANELS = {"representative": "대표 패널", "affected": "영향권 패널 · 비대표"}

FAVOR, OPPOSE, UNSURE, RESERVE = "찬성 쪽", "반대 쪽", "모름", "반대·유보"
MEASURE = {"favor": FAVOR, "oppose": OPPOSE, "unsure": UNSURE, "reserve": RESERVE}

# Top block, in display order. The banner comes before any number.
HEAD = "숫자로 먼저 보기(방향 참고값)"
BANNER = "합성 인물 모의 응답(실제 사람 0명)입니다. 여론조사가 아니며, 먼저 찾아갈 집단과 질문을 고르는 참고값입니다."
TAILS = {
    "archived": "미리 실행한 보관 결과(0원 열람)입니다. 새로 분석한 현재 값이 아닙니다.",
    "fallback": "판단 모델 없이 문장 모델 소표본({n})으로 대체한 결과입니다. 분포가 한쪽으로 쏠릴 수 있어 방향 참고만 하세요.",
    "mock": "화면 구조 확인용 가짜 숫자(0원 체험)입니다. 결과 수치에 뜻이 없습니다.",
}
SCALE = "규모: 합성 인물 풀 {pool} 중 인구 비율({strata})대로 뽑은 {n} 추정(판단 모델: {model}{reasons})"
SCALE_TEXT = "규모: 합성 인물 풀 {pool} 중 인구 비율({strata})대로 뽑은 {n}(문장 모델 {model} 소표본)"
REASONS = " · 이유 수집: 문장 모델 {n} 별도{split}"  # split: ", 대표 300·영향권 100"
DIST = "대표 패널 모의 분포: {parts}{swing}"
SWING = " (흔들림 폭 ±{pp})"
SWING_BASIS = " (흔들림 폭 ±{pp}: 대조 문장 {contrast}·선택지 순서 {order} 중 큰 값, 최소 3.0%p)"
SWING_UNKNOWN = " (흔들림 폭 미측정: 집단 차이를 강조하지 않음)"
UNSTABLE = ("불안정: 선택지 순서만 바꿔도 결과가 흔들립니다. 이 문항의 숫자는 방향 참고로 쓰기 어렵습니다. "
            "문항을 다듬어 다시 실행하세요.")
UNSURE_NOTE = "모의 응답의 '모름' 비율은 실제 유보율과 크게 다를 수 있습니다."
BASELINE = ("과거 공개 기준선(참고): {dist} [{source} · {method} · 모델 호출 0회]. "
            "과거 공개 집계의 추세이며, 현재 여론이나 합성 응답의 정답이 아닙니다.")
BASELINE_NONE = "과거 공개 기준선: 동일 문항 없음."
METHODS = {"last": "직전값", "linear": "직선 추세"}
OUTSIDE = "명단 밖: 19세 미만·외국인 주민·단체의 조직된 의견(맨 아래에서 따로 확인)."

# Group table (markdown, so an assistant can show it as is).
TABLE_HEAD = "집단별 모의 분포(대표 패널 · ▲: 100명 이상이고 찬성 쪽 차이가 흔들림 폭 ±{pp}를 넘음)"
TABLE_HEAD_NONE = "집단별 모의 분포(대표 패널 · 흔들림 폭 미측정이라 강조 없음)"
TABLE_COLUMNS = ("집단", "합성 인물", FAVOR, OPPOSE, UNSURE, "찬성 쪽 차이")
TABLE_COLUMNS_RESERVE = ("집단", "합성 인물", FAVOR, RESERVE, "찬성 쪽 차이")
TINY_CELL = "해석 불가(5명 미만)"
SMALL_CELL = "소집단 주의"
THIN_CELL = "표본 여유 부족"
AFFECTED = "영향권 패널(비대표 · 전체 비율에 합산하지 않음): {label} 합성 인물 {body}"

# Numbers that lead to a place to visit.
BASIS = "숫자 근거: {label} 합성 인물 {n} 중 {measure} 추정 {share}(전체 대비 {diff}, 흔들림 폭 초과)"
CANDIDATES_HEAD = "숫자로 본 방문 후보(협조 여부 미확인)"
CANDIDATE = "• {label}: 합성 인물 {n} 중 {measure} 추정 {share}(전체 대비 {diff}, 흔들림 폭 초과) → 찾아갈 곳 후보: {venue}"
NO_VENUE = "찾아갈 곳 자료 없음"

# Zero-cost re-aggregation ("60대만 보면?").
SLICE_HEAD = "다시 자른 숫자(0원 재집계)"
SLICE = "[{panel}] {filters}: 합성 인물 {body}"
SLICE_ALL = "전체"
DIFF = "(전체 대비 찬성 쪽 {diff})"
SLICE_SWING_UNKNOWN = " (흔들림 폭 미측정)"
TINY_NOTE = "(5명 미만: 비율 숨김 · 해석 불가, 찾아갈 곳의 단독 근거로 쓰지 않음)"
SMALL_NOTE = "소집단 주의: 인원이 적어 집단 특성으로 단정할 수 없습니다(현장 확인 참고용)."
THIN_NOTE = "표본 여유 부족: 차이가 흔들림 폭을 넘어도 찾아갈 곳 근거로는 약합니다."
INFLATE_NOTE = "AI는 학력·소득 격차를 실제보다 부풀리는 경향이 있습니다."
SLICE_REASONS = "이유(문장 모델 표본 {n} 중 이 조건, AI가 상상한 문장이며 실제 사람의 말이 아님): {quotes}"


def people(n: int) -> str:
    return f"{int(n):,}명"


def pool(n: int) -> str:
    n = int(n)
    return f"{n // 10_000:,}만 명" if n >= 10_000 and n % 10_000 == 0 else people(n)


def _half_up(value: float) -> int:
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def pct(share: float | None) -> str:
    """Whole percent; tiny or near-total shares keep a decimal so no minority is rounded away."""
    if share is None:
        return "—"
    value = 100 * share
    if value <= 0:
        return "0%"
    if value >= 100:
        return "100%"
    if value < 0.1:
        return "<0.1%"
    if value > 99.9:
        return ">99.9%"
    if value < 1 or value > 99:
        return f"{value:.1f}%"
    return f"{_half_up(value)}%"


def pp(value: float) -> str:
    return f"{value:.1f}%p"


def signed(diff_pp: float) -> str:
    whole = _half_up(diff_pp)
    return f"+{whole}%p" if whole > 0 else f"-{-whole}%p" if whole < 0 else "0%p"


def _split(total: float, shares: list[float]) -> list[int]:
    """Largest-remainder rounding so the parts add up to the total."""
    weight = sum(shares) or 1.0
    exact = [total * s / weight for s in shares]
    floor = [int(x) for x in exact]
    order = sorted(range(len(exact)), key=lambda i: -(exact[i] - floor[i]))
    for i in order[:int(round(total)) - sum(floor)]:
        floor[i] += 1
    return floor


def shares_text(favor, oppose=None, unsure=None, reserve=None) -> list[tuple[str, str]]:
    """(label, percent) pairs; whole percents add up to 100 when no share is extreme."""
    if oppose is None or unsure is None:
        reserve = reserve if reserve is not None else (None if favor is None else 1 - favor)
        pairs = [(FAVOR, favor), (RESERVE, reserve)]
    else:
        pairs = [(FAVOR, favor), (OPPOSE, oppose), (UNSURE, unsure)]
    values = [v for _, v in pairs]
    if all(v is not None and 0.01 <= v <= 0.99 for v in values):
        return [(label, f"{p}%") for (label, _), p in zip(pairs, _split(100, values))]
    return [(label, pct(v)) for label, v in pairs]


def counts_text(n: int, favor, oppose=None, unsure=None, reserve=None, *, three=False) -> list[tuple[str, int]]:
    """Estimated head counts (share × n, largest remainder); favor vs reserve unless three are asked for."""
    if favor is None:
        return []
    if three and oppose is not None and unsure is not None:
        return list(zip((FAVOR, OPPOSE, UNSURE), _split(n, [favor, oppose, unsure])))
    reserve = (oppose + unsure) if oppose is not None and unsure is not None else (
        reserve if reserve is not None else 1 - favor)
    return list(zip((FAVOR, RESERVE), _split(n, [favor, reserve])))


def tier(n: int) -> str:
    return "tiny" if n < TINY else "small" if n < SMALL else "thin" if n < MIN_GROUP else "full"


def share_body(n: int, favor, oppose=None, unsure=None, reserve=None) -> str:
    """'893명 중 찬성 쪽 39% · ...' with the small-group rules applied."""
    level = tier(n)
    if level in ("tiny", "small"):
        counts = counts_text(n, favor, oppose, unsure, reserve)
        if level == "tiny":
            return people(n) + " 중 " + " · ".join(f"{label} {people(c)}" for label, c in counts) + TINY_NOTE
        parts = [f"{label} {people(c)}({pct(c / n)})" for label, c in counts]
        return people(n) + " 중 " + " · ".join(parts) + " · " + SMALL_NOTE
    return people(n) + " 중 " + " · ".join(f"{label} {value}" for label, value in
                                          shares_text(favor, oppose, unsure, reserve))


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _row(row: dict) -> dict:
    keys = ("favor", "oppose", "unsure", "reserve")
    out = {k: _num(row.get(k)) for k in keys}
    if out["reserve"] is None and out["oppose"] is not None and out["unsure"] is not None:
        out["reserve"] = out["oppose"] + out["unsure"]
    return out


def view(result: dict) -> dict | None:
    """Read the engine's aggregate fields into one checked view; None when the result has no numbers."""
    overall = result.get("overall")
    if not isinstance(overall, dict) or not _num(overall.get("n")) or _num(overall.get("favor")) is None:
        return None
    contrast, order = _num(overall.get("contrast_pp")), _num(overall.get("order_pp"))
    swing = _num(overall.get("swing_pp"))
    if swing is None and (contrast is not None or order is not None):
        swing = max([FLOOR_PP] + [v for v in (contrast, order) if v is not None])
    if swing is not None:
        swing = max(swing, FLOOR_PP)
    unstable = order > UNSTABLE_PP if order is not None else bool(overall.get("unstable"))
    mode = result.get("mode")
    fallback = overall.get("model_kind") == "text" or bool(overall.get("fallback"))
    numbers = {
        "schema": "pp.numbers/1", "panel": "representative",
        "mode": mode if mode in ("archived", "mock") else "run", "fallback": fallback,
        "n": int(overall["n"]), "pool": int(_num(overall.get("pool")) or DEFAULT_POOL),
        "strata": list(overall.get("strata") or DEFAULT_STRATA), "model": str(overall.get("model") or "판단 모델"),
        **_row(overall), "swing_pp": swing, "contrast_pp": contrast, "order_pp": order, "unstable": unstable,
        "unsure_option": overall.get("unsure_option", True) is not False,
        "reasons_n": _num(overall.get("reasons_n")), "reasons_by_panel": overall.get("reasons_by_panel") or {},
    }
    numbers["rows"] = _table_rows(result.get("by_group") or {}, numbers)
    affected = overall.get("affected")
    numbers["affected"] = ({"label": str(affected.get("label") or "직접 영향 추정 집단"), "n": int(affected["n"]),
                            **_row(affected)} if isinstance(affected, dict) and _num(affected.get("n")) else None)
    numbers["highlights"] = _highlights(result.get("highlights") or [], numbers)
    baseline = result.get("baseline")
    numbers["baseline"] = baseline if isinstance(baseline, dict) and baseline.get("probabilities") else None
    numbers["slices"] = [s for s in (result.get("slice_results") or []) if isinstance(s, dict) and _num(s.get("n"))]
    return numbers


def _table_rows(by_group: dict, numbers: dict) -> list[dict]:
    rows, swing = [], numbers["swing_pp"]
    for axis in TABLE_AXES:
        for row in by_group.get(axis) or []:
            n = _num(row.get("n"))
            if not n or _num(row.get("favor")) is None:
                continue
            shares = _row(row)
            diff = 100 * (shares["favor"] - numbers["favor"])
            exceeds = row.get("exceeds") if isinstance(row.get("exceeds"), bool) else (
                swing is not None and abs(diff) > swing)
            # Cells under 30 people never get the mark; the table shows their badge instead.
            rows.append({"axis": axis, "group": str(row.get("group")), "n": int(n), **shares,
                         "diff_pp": round(diff, 1), "tier": tier(int(n)),
                         "exceeds": bool(exceeds) and swing is not None and n >= SMALL})
    return rows


def _highlights(items: list, numbers: dict) -> list[dict]:
    """Only groups of 100 or more that clear the wobble become visit evidence; none when unstable."""
    if numbers["unstable"] or numbers["swing_pp"] is None:
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        n, share, diff = _num(item.get("n")), _num(item.get("share")), _num(item.get("diff_pp"))
        if n is None or n < MIN_GROUP or share is None or diff is None or abs(diff) <= numbers["swing_pp"]:
            continue
        out.append({"label": str(item.get("label") or ""), "n": int(n), "share": share, "diff_pp": diff,
                    "measure": item.get("measure") if item.get("measure") in MEASURE else "reserve",
                    "issue_id": item.get("issue_id"), "groups": list(item.get("groups") or []),
                    "venue": item.get("venue")})
    return out


def top_lines(numbers: dict, *, tail: bool = True) -> list[str]:
    """Banner, tail, scale, distribution with its wobble, baseline and the off-roster pointer.

    ``tail=False`` drops the archived/mock tail when the same screen already starts with that notice.
    """
    lines = [HEAD, BANNER]
    if tail and numbers["mode"] in ("archived", "mock"):
        lines.append(TAILS[numbers["mode"]])
    if numbers["fallback"]:
        lines.append(TAILS["fallback"].replace("{n}", people(numbers["n"])))
    strata = "·".join(STRATA.get(s, AXIS.get(s, s)) for s in numbers["strata"])
    split = numbers["reasons_by_panel"]
    reasons = ""
    if numbers["reasons_n"] and not numbers["fallback"]:
        parts = "·".join(f"{PANELS[k].split(' ')[0]} {int(split[k]):,}" for k in PANELS if _num(split.get(k)))
        reasons = REASONS.format(n=people(numbers["reasons_n"]), split=f", {parts}" if parts else "")
    if numbers["fallback"]:
        lines.append(SCALE_TEXT.format(pool=pool(numbers["pool"]), strata=strata, n=people(numbers["n"]),
                                       model=numbers["model"]))
    else:
        lines.append(SCALE.format(pool=pool(numbers["pool"]), strata=strata, n=people(numbers["n"]),
                                  model=numbers["model"], reasons=reasons))
    parts = " · ".join(f"{label} {value}" for label, value in shares_text(
        numbers["favor"], numbers["oppose"], numbers["unsure"], numbers["reserve"]))
    if numbers["swing_pp"] is None:
        swing = SWING_UNKNOWN
    elif numbers["contrast_pp"] is None and numbers["order_pp"] is None:
        swing = SWING.format(pp=pp(numbers["swing_pp"]))
    else:
        swing = SWING_BASIS.format(pp=pp(numbers["swing_pp"]), contrast=_pp_or_none(numbers["contrast_pp"]),
                                   order=_pp_or_none(numbers["order_pp"]))
    lines.append(DIST.format(parts=parts, swing=swing))
    if numbers["unstable"]:
        lines.append(UNSTABLE)
    if numbers["unsure_option"] and numbers["oppose"] is not None:
        lines.append(UNSURE_NOTE)
    lines.append(baseline_line(numbers["baseline"]))
    lines.append(OUTSIDE)
    return lines


def _pp_or_none(value):
    return pp(value) if value is not None else "기록 없음"


def baseline_line(baseline: dict | None) -> str:
    if not baseline:
        return BASELINE_NONE
    options, values = baseline.get("options") or [], baseline.get("probabilities") or []
    dist = " · ".join(f"{o} {p}%" for o, p in zip(options, _split(100, values))) if values else ""
    years = baseline.get("history_years") or []
    source = baseline.get("source_name") or "공개 집계"
    if years:
        source = f"{years[-1]} {source}"
    return BASELINE.format(dist=dist, source=source, method=METHODS.get(baseline.get("method"), "기준선"))


def compact_rows(numbers: dict) -> list[dict]:
    """Rows kept when the card runs out of room: every age band and any highlighted cell."""
    return [r for r in numbers["rows"] if r["axis"] == "age_band" or r["exceeds"]]


def table_lines(numbers: dict, rows: list[dict] | None = None) -> list[str]:
    rows = numbers["rows"] if rows is None else rows
    if not rows:
        return []
    reserve_only = any(r["oppose"] is None or r["unsure"] is None for r in rows)
    columns = TABLE_COLUMNS_RESERVE if reserve_only else TABLE_COLUMNS
    head = TABLE_HEAD.format(pp=pp(numbers["swing_pp"])) if numbers["swing_pp"] is not None else TABLE_HEAD_NONE
    lines = [head, "", "| " + " | ".join(columns) + " |", "|" + "---|" + "---:|" * (len(columns) - 1)]
    for r in rows:
        if r["tier"] in ("tiny", "small"):
            counts = counts_text(r["n"], r["favor"], r["oppose"], r["unsure"], r["reserve"], three=not reserve_only)
            cells = [people(c) if r["tier"] == "tiny" else f"{people(c)}·{pct(c / r['n'])}" for _, c in counts]
            note = TINY_CELL if r["tier"] == "tiny" else f"{signed(r['diff_pp'])} {SMALL_CELL}"
        else:
            cells = [value for _, value in shares_text(r["favor"], None if reserve_only else r["oppose"],
                                                       None if reserve_only else r["unsure"], r["reserve"])]
            note = signed(r["diff_pp"])
            if r["exceeds"]:
                note += " ▲" if r["tier"] == "full" else " " + THIN_CELL
        lines.append("| " + " | ".join([r["group"], people(r["n"]), *cells, note]) + " |")
    lines.append("")
    return lines


def affected_line(numbers: dict) -> str | None:
    a = numbers["affected"]
    if not a:
        return None
    return AFFECTED.format(label=a["label"], body=share_body(a["n"], a["favor"], a["oppose"], a["unsure"], a["reserve"]))


def basis_line(h: dict) -> str:
    return BASIS.format(label=h["label"], n=people(h["n"]), measure=MEASURE[h["measure"]], share=pct(h["share"]),
                        diff=signed(h["diff_pp"]))


def candidate_line(h: dict, venue: str | None) -> str:
    return CANDIDATE.format(label=h["label"], n=people(h["n"]), measure=MEASURE[h["measure"]], share=pct(h["share"]),
                            diff=signed(h["diff_pp"]), venue=venue or NO_VENUE)


def slice_text(item: dict, numbers: dict | None = None, warnings: list | None = None) -> str:
    """One re-aggregated slice. Panels are never mixed: any other panel name is refused."""
    panel = item.get("panel") or "representative"
    if panel not in PANELS:
        raise ValueError("panel_must_be_representative_or_affected")
    filters = item.get("filters") or {}
    label = " · ".join(str(v) for v in filters.values()) or SLICE_ALL
    shares = _row(item)
    n = int(item["n"])
    text = SLICE.format(panel=PANELS[panel], filters=label,
                        body=share_body(n, shares["favor"], shares["oppose"], shares["unsure"], shares["reserve"]))
    level = tier(n)
    swing = numbers.get("swing_pp") if numbers else None
    if numbers and panel == "representative" and level in ("thin", "full") and shares["favor"] is not None:
        diff = 100 * (shares["favor"] - numbers["favor"])
        text += " " + DIFF.format(diff=signed(diff))
        if level == "thin" and swing is not None and abs(diff) > swing:
            text += " " + THIN_NOTE
    if level not in ("tiny", "small"):
        text += SWING.format(pp=pp(swing)) if swing is not None else SLICE_SWING_UNKNOWN
    if INFLATED_AXES & set(filters):
        text += " " + INFLATE_NOTE
    reasons = [public_rules.check_output(_clip(r), "", warnings if warnings is not None else [])
               for r in (item.get("reasons") or [])[:2] if r]
    if reasons:
        text += "\n  " + SLICE_REASONS.format(n=people(item.get("reasons_n") or n), quotes=" / ".join(reasons))
    return text


def _clip(value, limit=80) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


@dataclass(frozen=True)
class Forbidden:
    name: str
    pattern: re.Pattern
    why: str
    instead: str


_PCT = r"\d+(?:\.\d+)?\s*%"
FORBIDDEN: tuple[Forbidden, ...] = (
    Forbidden("survey", re.compile(r"국민\s*여론|(?<![가-힣])민심|(?<![가-힣])민의(?=$|[은는이가를을도,.\s])|(?:설문|여론\s*조사|조사)\s*결과|응답자|응답률"),
              "실제 사람에게 물은 조사가 아닙니다.", "합성 인물 모의 응답, 모의 패널 기준"),
    Forbidden("definite", re.compile(r"나타났|조사됐|조사되었|드러났|확인됐|확인되었"),
              "실측한 사실처럼 읽힙니다.", "~로 추정됐다, 현장 확인이 필요하다"),
    Forbidden("generalize", re.compile(r"대다수|대부분|과반|절반\s*이상|다수가|(?:국민|시민|주민|사람)들?(?:은|는)\s*(?:찬성|반대)"),
              "합성 속성을 현실 집단 전체로 넓힙니다.", "60대 합성 인물 N명 중 반대·유보 추정 X%"),
    Forbidden("real_subject", re.compile(
        r"(?<![가-힣])(?:국민|시민|주민|도민|유권자|응답자|어르신|노인|청년|사람들)(?:의|은|는|이|가)?\s*" + _PCT
        + r"|\d+대\s*(?:의|는|은|이|가)?\s*" + _PCT + r"|" + _PCT + r"\s*(?:가|이|는|은)\s*(?:찬성|반대|지지|모름|유보)"),
              "숫자의 주어가 실제 사람처럼 읽힙니다.", "합성 인물 N명 중 찬성 쪽 X%"),
    Forbidden("sampling_error", re.compile(r"신뢰\s*수준|표본\s*오차|오차\s*범위|통계적으로\s*유의|유의미한\s*차이"),
              "확률표본의 오차가 아니라 모델 흔들림입니다.", "흔들림 폭 ±X%p(대조 문장·선택지 순서 기준)"),
    Forbidden("rate_rank", re.compile(r"찬성률|반대율|지지율|\d+\s*위(?![가-힣])|1등|수급\s*(?:대상|자격)\s*(?:확정|해당)"),
              "조사 비율·순위·자격 판정처럼 읽힙니다.", "찬성 쪽 X%, 모의 추정치(제도 자격과 무관)"),
    Forbidden("panel_mix", re.compile(r"대표\s*(?:패널)?\s*[\d,]+\s*명?\s*\+\s*영향권|영향권[^.\n]{0,15}(?:더해|합쳐|합산해)"),
              "비대표 영향권 패널을 전체 분포에 섞습니다.", "대표 패널 기준 X% / 영향권 N명 별도"),
    Forbidden("tiny_percent", re.compile(r"(?<![\d,])[1-4]\s*명\s*중[^\n]{0,30}?" + _PCT
                                         + r"|" + _PCT + r"[^\n]{0,20}?(?<![\d,])[1-4]\s*명\s*중"),
              "5명 미만 칸에 비율을 붙입니다.", "4명 중 반대·유보 3명(비율 숨김)"),
    Forbidden("borrowed_error", re.compile(r"\bPew\b|퓨\s*리서치|±\s*12\s*(?:점|%p)"),
              "다른 조사의 오차를 이 문항의 오차처럼 붙입니다.", "이 실행의 흔들림 폭만 씁니다"),
)
STANCE_SHARE = re.compile(r"(?:찬성|반대|모름|유보)[^\n%|]{0,8}?" + _PCT)
CONTEXT = re.compile(r"합성 인물|모의|패널|기준선|추정")


def violations(text: str) -> list[tuple[str, str]]:
    """(rule name, matched words) for every forbidden expression; table rows rely on their header."""
    found = [(rule.name, m.group()) for rule in FORBIDDEN for m in rule.pattern.finditer(text)]
    for line in text.splitlines():
        if not line.lstrip().startswith("|") and STANCE_SHARE.search(line) and not CONTEXT.search(line):
            found.append(("no_subject", line.strip()[:60]))
    return found
