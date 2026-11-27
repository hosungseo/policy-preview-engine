"""Offline views of existing public runs, never fresh model output.

Packaged excerpts retain the original qualitative fields and a hash of their source.
Stored probability means are retained; missing group distributions are never invented.
"""
import json
from importlib.resources import files

from . import attribution, public_rules, visit_shared

EXAMPLES = ("subway-free-ride", "judge-attendance", "life-safety-decree", "rural-basic-income")
LABEL = "공개 예시 · 보관 결과"
NOTICE = "공개 예시의 보관 결과입니다. 지금 새로 분석한 결과가 아니며, 열람 비용은 0원입니다."


# Editorial interview prompts derived from the archived issues, not archive quotes.
FIELD_QUESTIONS = {
    "subway-free-ride": {
        "i1": "무임에서 할인으로 바뀌면 평소 이동과 생활비에 어떤 변화가 생기나요?",
        "i2": "세대별로 혜택을 받기 시작하는 시점이 달라질 때 어떤 점을 확인해야 하나요?",
        "i3": "도시철도가 없는 지역에서 평소 어떤 교통편을 이용하고, 버스 지원은 어디에 필요한가요?",
        "i4": "무임 대상에서 빠지는 기간이나 기초연금 수급 여부에 따라 지원이 비는 경우는 무엇인가요?",
        "i5": "요금과 운영기관 재정, 현장 안내에서 어떤 변화를 확인해야 하나요?",
    },
    "judge-attendance": {
        "i1": "근무시간 관리가 업무 자율성과 판단에 어떤 영향을 줄 수 있나요?",
        "i2": "재판을 기다리는 과정에서 어느 단계가 가장 오래 걸리고 어떤 불편이 있었나요?",
        "i3": "재판 지연으로 의뢰인과 실무자가 겪는 불편은 무엇이며, 근무시간 관리로 줄일 수 있나요?",
        "i4": "판결문 작성과 기록 검토에서 정해진 근무시간 안에 끝내기 어려운 업무는 무엇인가요?",
        "i6": "재판 지연이 계약이나 분쟁 처리에 어떤 영향을 주었나요?",
    },
    "rural-basic-income": {
        "i1": "지원 대상이 아닌 지역에서 사업의 의미와 재정 부담을 어떻게 보고 계신가요?",
        "i2": "지원금이 생긴다면 어떤 생활비에 먼저 쓰시겠으며 이용에 어려움은 없을까요?",
        "i3": "지원 지역을 정하는 기준에서 이해하기 어렵거나 빠졌다고 느끼는 조건은 무엇인가요?",
        "i5": "농촌에 계속 거주할지 결정할 때 지원금 외에 어떤 조건이 필요한가요?",
        "i6": "시범사업이 끝난 뒤 지원이 중단되면 생활 계획에 어떤 변화가 생기나요?",
    },
    "life-safety-decree": {
        "i1": "현장에서 사고를 겪으면 어떤 보호가 필요하고 지원을 요청할 때 어디에서 막히나요?",
        "i2": "교육이나 평가 절차가 늘어나면 기존 업무의 어떤 부분에 부담이 생기나요?",
        "i3": "사고 피해자와 가족이 지원을 요청하고 회복하는 과정에서 어떤 도움이 필요한가요?",
        "i4": "부처별 안전기준이 달라 업무에 어려움을 겪은 경우는 무엇인가요?",
        "i5": "지역에서 큰 사고가 나면 공동체 회복에 어떤 지원이 필요한가요?",
        "i6": "구조나 피해자 지원 활동을 하다 다치거나 심리적 어려움을 겪을 때 어떤 보호가 필요한가요?",
    },
}


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
        who.append({"issue_id": issue["id"], "groups": issue["groups"], "questions": [FIELD_QUESTIONS[example][issue["id"]]],
                    "reaction_quotes": questions, "question_basis": "보관 쟁점을 바탕으로 편집한 담당자용 현장 질문입니다. 보관 원문 인용이 아닙니다.",
                    "clause_ids": issue["segments"],
                    "venues": list(dict.fromkeys(" · ".join(filter(None, (o.get("where"), o.get("method")))) for o in contacts if o.get("where") or o.get("method"))),
                    "basis": "보관된 쟁점·질문과 집단 이름으로 연결한 접점 후보입니다. 현장에서 확인하세요."})
    # Keep original clause order, not the old frequency or model probability order.
    order = {s["id"]: n for n, s in enumerate(data["segments"])}
    who.sort(key=lambda row: order.get(next(i for i in issues if i["id"] == row["issue_id"])["segments"][0], len(order)))
    missing = [{"group": row["who"], "reason": "합성 인물 자료로 대신할 수 없어 직접 확인해야 합니다.", "route": row["route"]}
               for row in visit_shared.missing_people(data["policy_text"])]
    for group in data["missing"]:
        missing.append({"group": group, "reason": "보관된 가상 공청회에서 빠진 관점입니다.", "route": "관련 기관·현장 간담회에서 직접 확인하세요."})
    return public_rules.envelope({
        "schema": "pp.run/4", "mode": "archived", "result_label": LABEL, "trial_notice": NOTICE,
        **data.get("numbers", {}),
        "example": example, "title": data["title"], "clauses": clauses,
        "issues": [{k: i[k] for k in ("id", "title", "summary")} for i in issues],
        "who_to_ask": who, "questions": data["questions"], "outreach": data["outreach"],
        "questions_notice": "questions는 보관 결과의 원문 인용입니다. 담당자가 물을 편집 질문은 who_to_ask의 questions입니다.",
        "missing_perspectives": missing, "conditions": {"models": data["models"]},
        "archive": data["archive"], "policy_source": data["source"],
        "attribution": attribution.build(), "budget": {"cost_usd": 0, "cost_status": "known",
            "scope": "이번 보관 결과 열람 비용입니다. 과거 분석 비용은 포함하지 않습니다."},
        "warnings": ["보관 원문은 인용으로, 담당자용 현장 질문은 편집한 초안으로 구분했습니다. 접점은 집단 이름으로 연결한 후보이며 협조 여부는 확인하지 않았습니다."],
        "grouping": {"basis": "archived_clause_order"},
    })
