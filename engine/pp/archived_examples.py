"""Offline views of existing public runs, never fresh model output.

Packaged excerpts retain the original qualitative fields and a hash of their source.
No historic opinion counts, probabilities or named personas enter this view.
"""
import json
from importlib.resources import files

from . import attribution, public_rules, visit_shared

EXAMPLES = ("subway-free-ride", "judge-attendance", "life-safety-decree", "rural-basic-income")
LABEL = "공개 예시 · 보관 결과"
NOTICE = "공개 예시의 보관 결과입니다. 지금 새로 분석한 결과가 아니며, 열람 비용은 0원입니다."


def load(example):
    data = json.loads(files("pp").joinpath("data", "examples", example + ".json").read_text(encoding="utf-8"))
    issues = data["issues"]
    clauses = [{**s, "issues": [i["id"] for i in issues if s["id"] in i["segments"]]} for s in data["segments"]]
    who = []
    for issue in issues:
        questions = [q["question"] for q in data["questions"] if q["issue_id"] == issue["id"]]
        if not questions:
            continue
        # Original outreach groups often refine an issue group (e.g. age + region).
        contacts = [o for o in data["outreach"] if any(g == o["group"] or g in o["group"] for g in issue["groups"])]
        who.append({"issue_id": issue["id"], "groups": issue["groups"], "questions": questions,
                    "clause_ids": issue["segments"],
                    "venues": list(dict.fromkeys(o["where"] for o in contacts if o["where"])),
                    "basis": "보관된 쟁점·질문과 집단 이름으로 연결한 접점 후보입니다. 현장에서 확인하세요."})
    # Keep original clause order, not the old frequency or model probability order.
    order = {s["id"]: n for n, s in enumerate(data["segments"])}
    who.sort(key=lambda row: order.get(next(i for i in issues if i["id"] == row["issue_id"])["segments"][0], len(order)))
    missing = [{"group": row["who"], "reason": "합성 인물 자료로 대신할 수 없어 직접 확인해야 합니다.", "route": row["route"]}
               for row in visit_shared.missing_people(data["policy_text"])]
    for group in data["missing"]:
        missing.append({"group": group, "reason": "보관된 가상 공청회에서 빠진 관점입니다.", "route": "관련 기관·현장 간담회에서 직접 확인하세요."})
    return public_rules.envelope({
        "schema": "pp.run/3", "mode": "archived", "result_label": LABEL, "trial_notice": NOTICE,
        "example": example, "title": data["title"], "clauses": clauses,
        "issues": [{k: i[k] for k in ("id", "title", "summary")} for i in issues],
        "who_to_ask": who, "questions": data["questions"], "outreach": data["outreach"],
        "missing_perspectives": missing, "conditions": {"models": data["models"]},
        "archive": data["archive"], "policy_source": data["source"],
        "attribution": attribution.build(), "budget": {"cost_usd": 0, "cost_status": "known",
            "scope": "이번 보관 결과 열람 비용입니다. 과거 분석 비용은 포함하지 않습니다."},
        "warnings": ["보관 결과의 질문을 옮겼습니다. 접점은 집단 이름으로 연결한 후보이며 협조 여부는 확인하지 않았습니다."],
        "grouping": {"basis": "archived_clause_order"},
    })
