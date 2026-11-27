"""Consultation plan (의견수렴 계획서 초안): numbers and quotes from code, prose from earlier LLM steps."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import attribution, config

KST = ZoneInfo("Asia/Seoul")

LIMITS = [
    "대표 패널과 영향권 패널은 따로 집계합니다. 영향권: 전체 비율로 읽지 않음.",
    "이 계획서는 합성 인물(AI)의 반응을 바탕으로 만든 초안이며, 실제 여론조사 결과가 아닙니다.",
    "AI 반응은 합의를 부풀리고 중도로 몰리는 경향이 있어 찬반 비율은 방향 참고용으로만 씁니다.",
    "기본 합성 인물(Nemotron-Personas-Korea)은 19세 이상이며 소득 정보가 없습니다. 애드온의 가구 소득은 통계로 배정한 구간(가정)이라 "
    "지원 금액·수급 자격·상환 능력을 계산하는 데 쓰지 않습니다. 구간의 가운데 값을 그 사람의 금액으로 쓰지 않습니다.",
    config.FAMILY_NOTE,
    "몇 명뿐인 교차 칸(예: 시군구 × 직업)의 차이는 집단 차이로 단정하지 않습니다. 시도·연령대·성별 합계가 맞아도 다른 속성의 조합까지 "
    "현실과 같다고 보지 않습니다.",
    "‘찾아가 들어야 할 집단’의 침묵 비율은 AI가 추정한 의견 제출 의향에 기반하므로 현장 확인이 필요합니다.",
    "수정안 비교와 참여 방식 확률은 합성 인물에 대한 Jev의 추정이며, 효과가 날짜·나이 계산에 달린 수정안은 잘못 읽을 수 있습니다.",
]


def local_date(iso: str) -> str:
    """Run timestamps are stored in UTC; documents show the Korean calendar date."""
    return datetime.fromisoformat(iso).astimezone(KST).date().isoformat()


def _clarity_items(clarity: dict | None, labels: dict[str, str]) -> dict | None:
    """Provisions to rewrite (indicators Jev flagged) and notice items the text seems to lack."""
    if not clarity:
        return None
    names = {i["key"]: i["label"] for i in clarity["indicators"]}
    clauses = [{"segment_id": c["segment_id"], "label": labels.get(c["segment_id"], c["segment_id"]),
                "flags": [{"key": k, "label": names[k], "p": c["values"][k]} for k in c["flags"]]}
               for c in clarity["clauses"] if c["flags"]]
    missing = [d for d in clarity["document"] if d["p"] < clarity.get("threshold", 0.5)]
    return {"clauses": clauses, "missing": missing}


def build_plan(policy: dict, analysis: dict, segments: list[dict], qa: list[dict], meta: dict,
               clarity: dict | None = None) -> dict:
    labels = {s["id"]: s["label"] for s in segments}
    issues = [{
        "id": it["id"], "title": it["title"], "stance": it["stance"], "n": it["n"], "share": it["share"],
        "mean": it["mean"], "summary": it["summary"],
        "by_panel": it.get("by_panel"), "basis": "rep",
        "segments": [labels[s] for s in it["segments"] if s in labels],
        "groups": [g["group"] for g in it["groups"]],
        "quote": it["quotes"][0]["text"] if it["quotes"] else "",
        **({"jev_mean": it["jev_mean"]} if "jev_mean" in it else {}),
    } for it in analysis["issues"][:5]]
    outreach = [{**{k: o[k] for k in ("kind", "group", "n", "direct", "oppose", "silent", "channels", "suggestion")},
                 "panel": o.get("panel"), "caution": o.get("caution"),
                 **({"methods": o["methods"]} if o.get("methods") else {})} for o in analysis["outreach"]]
    alternatives = sorted(((analysis.get("alternatives") or {}).get("items") or []),
                          key=lambda it: it.get("net_reserve", it["d_reserve"]))
    alternatives = [{k: it[k] for k in ("id", "title", "text", "source_title", "source_n", "source_example", "n",
                                        "d_favor", "d_reserve", "d_mean")}
                    | {k: it[k] for k in ("net_favor", "net_reserve", "net_mean", "source_n_aff") if k in it}
                    | {"movers": it["movers"][:2]} for it in alternatives]
    explain = None
    ex = ((analysis.get("jev") or {}).get("explain"))
    if ex:
        clauses = sorted(({"segment_id": sid, "label": labels.get(sid, sid), "p": p} for sid, p in ex["overall"].items()),
                         key=lambda c: -c["p"])
        groups = [g for g in ex["understand"].get("education_level", []) if not g["small"]]
        hardest = min(groups, key=lambda g: g["mean"]) if groups else None
        explain = {"clauses": clauses[:3], "understand": ex["understand"]["overall"],
                   "hardest": {"group": hardest["group"], "mean": hardest["mean"]} if hardest else None}
    suggestions = [{"title": s["title"], "n": s["n"], **({"n_aff": s["n_aff"]} if s.get("n_aff") is not None else {}), "example": s["example"],
                    "caution": s.get("caution")} for s in analysis["suggestions"][:6]]
    overview = {
        "title": policy["title"], "kind": policy["kind"], "agency": policy.get("agency", ""),
        "panel": f"대표 패널 {analysis['overall']['n']}명 + 영향권 패널 {analysis['overall_aff']['n']}명",
        "created_at": local_date(meta["created_at"]), "panel_version": meta.get("panel_version"),
        "source_revision": meta.get("source_revision"),
    }
    return {"overview": overview, "issues": issues, "outreach": outreach, "qa": qa,
            "suggestions": suggestions, "alternatives": alternatives, "explain": explain,
            "clarity": _clarity_items(clarity, labels), "limits": LIMITS, "attribution": attribution.build(meta)}
