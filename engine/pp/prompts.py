"""Prompt templates. mock.py parses the marked structures ([정책], 'r1|', '- ', '## 그룹:', 'i1|')."""
from __future__ import annotations

from . import config, voice

_JSON_ONLY = "반드시 JSON 객체 하나만 출력한다."
REACT_SYSTEM = ("당신은 아래 [인물] 본인이다. 인물의 처지와 이해관계에 비추어 솔직하게 반응한다. "
                "중립적으로 보이려 애쓰지 말고, 모르는 것은 모른다고 한다. " + _JSON_ONLY)
TARGET_SYSTEM = "당신은 정책 영향 분석가다. " + _JSON_ONLY
CLUSTER_SYSTEM = "당신은 의견 분석가다. 주어진 내용만 근거로 묶고, 없는 내용을 지어내지 않는다. " + _JSON_ONLY
OCC_SYSTEM = "당신은 한국표준직업분류 전문가다. " + _JSON_ONLY
OUTREACH_SYSTEM = "당신은 정부 의견수렴 설계 담당자다. 주어진 근거 안에서만 제안한다. " + _JSON_ONLY
HEARING_SYSTEM = "당신은 가상 공청회에 참석한 아래 [인물] 본인이다. 인물의 처지에서 말한다. " + _JSON_ONLY
SUMMARY_SYSTEM = "당신은 공청회 기록 담당자다. 회의록에 있는 내용만 정리한다. " + _JSON_ONLY
AMEND_SYSTEM = "당신은 정책 문안을 다듬는 입법 실무자다. 주어진 제안 안에서만 고친다. " + _JSON_ONLY
QA_SYSTEM = "당신은 정책 설명 자료를 준비하는 공무원이다. 주어진 쟁점만 근거로 쓴다. " + _JSON_ONLY

ROUND_TASKS = {
    1: "사회자가 입장 발표를 요청했다. 안건에 대한 자신의 입장과 이유를 말하라.",
    2: "사회자가 반론을 요청했다. 앞선 참석자 가운데 한 명 이상을 이름으로 부르며 동의하거나 반박하라.",
    3: "사회자가 보완안을 요청했다. 정부가 무엇을 바꾸면 받아들일 수 있는지 구체적인 보완안을 하나 말하라.",
}
HEARING_POLICY_LIMIT = 900


def clip(text: str | None, limit: int) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= limit else t[: limit - 1] + "…"


def hearing_policy_context(policy_text: str) -> dict:
    normalized = " ".join(policy_text.split())
    shown = clip(policy_text, HEARING_POLICY_LIMIT)
    return {"policy_truncated": len(normalized) > HEARING_POLICY_LIMIT,
            "shown_chars": len(shown), "total_chars": len(normalized), "original_chars": len(policy_text),
            "length_basis": "whitespace_collapsed_including_ellipsis", "policy_excerpt": shown}


def persona_profile(p: dict, long: bool = True) -> str:
    lines = [
        f"이름: {p.get('name') or '(이름 없음)'}",
        f"성별·나이: {p['sex']}, {p['age']}세",
        f"사는 곳: {p['district']} ({config.PROVINCE_DISPLAY.get(p['province'], p['province'])})",
        f"직업: {p['occupation']}",
        f"학력: {p['education_level']} / 혼인: {p['marital_status']}",
        f"가구: {p['family_type']} / 주거: {p['housing_type']}",
        "",
        clip(p.get("persona"), 300),
    ]
    if long:
        lines += [clip(p.get("professional_persona"), 300), clip(p.get("family_persona"), 300),
                  clip(p.get("cultural_background"), 300)]
    return "\n".join(lines)


def react_prompt(p: dict, policy_text: str) -> str:
    return f"""[인물]
{persona_profile(p)}

[말투 지침]
{voice.voice_guide(p)}

[정책]
{policy_text.strip()}
[/정책]

위 정책을 처음 접했다고 생각하고 이 인물로서 답하라. 항목:
· support: 지지도 정수. -2 강한 반대, -1 반대, 0 중립, 1 찬성, 2 강한 찬성
· impact: 이 정책이 내 생활에 미치는 영향. "직접", "간접", "무관" 중 하나
· trigger_quote: 반응을 일으킨 정책 문구를 [정책]에서 글자 그대로 복사(8~40자). 특별한 문구가 없으면 가장 관련 있는 문구
· reason: 이 인물의 말투로 1~2문장. 자기 처지가 드러나게
· concerns: 우려 키워드 0~3개(각 2~8자)
· hopes: 기대 키워드 0~3개(각 2~8자)
· suggestion: 정부에 바라는 보완점 한 문장. 없으면 빈 문자열
· would_comment: 이 정책의 공식 의견수렴(입법예고 의견 제출, 공청회 등)에 스스로 의견을 낼 것 같으면 true, 아니면 false
· channel: 이 사람이 이런 소식을 주로 접하거나 의견을 말할 만한 곳 한 가지(예: 주민센터, 경로당, 동네 단톡방, 유튜브, 노조, 협회, 없음)

JSON 형식: {{"support": 0, "impact": "간접", "trigger_quote": "", "reason": "", "concerns": [], "hopes": [], "suggestion": "", "would_comment": false, "channel": ""}}"""


def target_prompt(policy_text: str, occupations: list[str] | None = None) -> str:
    """occupations: every occupation name in the persona DB; without it the model guesses names that may not exist."""
    provinces = ", ".join(config.PROVINCE_DISPLAY.values())
    housing = ", ".join(config.HOUSING_ORDER)
    education = ", ".join(config.EDUCATION_ORDER)
    vocab = f"\n[직업명 목록]\n{', '.join(occupations)}\n[/직업명 목록]\n" if occupations else ""
    pick = ("\n   occupation_like에는 [직업명 목록]의 이름을 그대로 적는다. 목록의 이름은 그 직업(과 그 직업의 구직자)만 찾고, "
            "목록에 없는 말은 직업명의 일부로 찾아서 엉뚱한 직업까지 걸린다."
            if occupations else
            "\n   occupation_like는 직업명의 일부로 찾으므로, 다른 직업명에도 들어가는 짧은 말은 피한다.")
    return f"""[정책]
{policy_text.strip()}
[/정책]
{vocab}
이 정책으로 생활이 직접 달라질 사람들을 한국인 인물 데이터베이스에서 찾으려 한다. 다음을 만들어라.
1) filters: 속성 조건 묶음 1~4개. 한 묶음 안의 조건은 모두 만족(AND), 묶음끼리는 OR.
   쓸 수 있는 키: occupation_like(직업명 부분 문자열 목록), age_min, age_max, province_in(다음 값 중에서: {provinces}),
   family_type_like(가구 유형 부분 문자열 목록, 예: 혼자, 한부모, 자녀), housing_type_in(다음 값 중에서: {housing}),
   education_in(다음 값 중에서: {education}), sex(남자 또는 여자).
   직업명은 한국표준직업분류 식 표현이다(예: 택시 운전원, 곡물 재배자, 소규모 상점 경영자, 요양보호사, 초등학교 교사).{pick}
   직접 대상이 드문 직업이면 그 일과 가까이 얽힌 사람(함께 일하는 직원, 그 서비스를 받는 사람)도 따로 묶음으로 넣는다.
   직업명에는 일하는 기관 이름이 들어가지 않는다(예: 시청·구청 직원은 '지방행정 사무원').
2) keywords: 인물의 직업·가족·생활 서술에서 찾을 검색어 3~8개. 반드시 3글자 이상(예: 지하철로, 농사를, 어린이집).
   영향받는 사람만 가려내는 말을 쓴다. 출퇴근, 근무시간처럼 누구의 일상 서술에나 나오는 말은 쓰지 않는다.
3) semantic_query: 영향받을 사람을 묘사하는 한두 문장.
4) rationale: 왜 이 사람들이 영향권인지 한 문장.

JSON 형식: {{"filters": [{{"occupation_like": ["..."], "age_min": 60}}], "keywords": ["..."], "semantic_query": "...", "rationale": "..."}}"""


def cluster_prompt(title: str, lines: str, min_k: int, max_k: int, what: str = "반응") -> str:
    return f"""정책: {title}
아래는 합성 인물들의 {what}이다. 한 줄 형식은 id|내용이다.
{lines}

{what}을 주제별로 {min_k}~{max_k}개로 묶어라.
· title: 15자 안팎의 명사구
· stance: "우려", "기대", "혼재" 중 하나
· summary: 한 문장
· member_ids: 이 묶음에 속하는 id 목록. 한 id는 한 묶음에만 넣고, 억지로 넣기 어려운 id는 빼도 된다.
{what}에 없는 내용을 지어내지 않는다.

JSON 형식: {{"issues": [{{"title": "...", "stance": "우려", "summary": "...", "member_ids": ["r1", "r7"]}}]}}"""


def occupation_prompt(occupations: list[str]) -> str:
    items = "\n".join(f"- {o}" for o in occupations)
    return f"""다음 직업명 각각을 한국표준직업분류 대분류 하나로 분류하라.
대분류: {", ".join(config.OCCUPATION_MAJORS)}
무직, 주부, 학생, 은퇴자는 "무직·기타"로 분류한다.

직업명 목록:
{items}

JSON 형식: {{"map": {{"직업명": "대분류"}}}}"""


def outreach_block(c: dict, quotes: list[str]) -> str:
    said = "\n".join(f'  "{q}"' for q in quotes) or "  (반대 발언 없음)"
    heard = ", ".join(c["channels"]) or "응답 없음"
    methods = ", ".join(f"{m['label']} {round(m['p'] * 100)}%" for m in c.get("methods") or []) or "자료 없음"
    return (f"## 그룹: {c['group']}\n"
            f"인원 {c['n']}명, 직접 영향 {round(c['direct'] * 100)}%, 반대·유보(반대 또는 중립) {round(c['oppose'] * 100)}%, "
            f"스스로 의견을 내지 않을 사람 {round(c['silent'] * 100)}%\n"
            f"주로 소식을 접하는 곳(인물 응답): {heard}\n"
            f"방식별 참여 확률(Jev 추정, 높은 순): {methods}\n반대 발언:\n{said}")


def outreach_prompt(title: str, blocks: list[str]) -> str:
    body = "\n\n".join(blocks)
    return f"""정책: {title}
아래 집단은 이 정책의 영향을 크게 받고 반대하거나 판단을 유보하는 사람이 많으며, 공식 의견수렴에 스스로 나서지 않을 것으로 보이는 집단이다.
수치와 발언, 소식을 접하는 곳을 근거로 이들의 목소리를 직접 들을 방법을 그룹마다 제안하라.
방식은 참여 확률이 높은 것을 우선하되, 소식을 접하는 곳과 맞춘다.

{body}

그룹마다 group(위 그룹명을 글자 그대로), method(방식), where(장소·경로), when(시기), why(위 근거를 든 한 문장)를 쓴다.
JSON 형식: {{"items": [{{"group": "...", "method": "...", "where": "...", "when": "...", "why": "..."}}]}}"""


def hearing_prompt(p: dict, policy_text: str, agenda: list[str], reaction: dict, transcript: str, rnd: int) -> str:
    items = "\n".join(f"{i + 1}. {a}" for i, a in enumerate(agenda))
    return f"""[인물]
{persona_profile(p, long=False)}

[말투 지침]
{voice.voice_guide(p)}

[정책 요약]
{hearing_policy_context(policy_text)['policy_excerpt']}

[안건]
{items}

[이 인물이 처음 보인 반응]
지지도 {reaction['support']}, 이유: {reaction['reason']}

[지금까지 회의록]
{transcript or '(아직 없음)'}

{ROUND_TASKS[rnd]}
2~4문장, 이 인물의 말투로 말한다. 다른 참석자의 말을 지어내지 않는다.
JSON 형식: {{"text": "..."}}"""


def summary_prompt(title: str, transcript: str) -> str:
    return f"""정책: {title}
[회의록]
{transcript}

회의록만 근거로 정리하라.
· agreements: 참석자들이 대체로 동의한 점 1~2개
· disagreements: 의견이 갈린 점 1~2개
· missing: 이 자리에 없어서 추가로 들어야 할 사람 1~2개
JSON 형식: {{"agreements": ["..."], "disagreements": ["..."], "missing": ["..."]}}"""


def qa_prompt(title: str, issue_lines: str, *, consultation: bool = False) -> str:
    task = ("실제 의견수렴에서 담당자가 당사자에게 물을 열린 질문을 쟁점마다 하나 이상 써라. "
            "질문에 결론을 미리 넣거나 찬반을 유도하지 말라. answer에는 당사자 답변을 지어내지 말고 "
            "현장에서 확인·기록할 항목을 써라." if consultation else
            "설명회나 공청회에서 나올 예상 질문 5개와, 담당 부서가 준비할 답변 방향을 써라.")
    question_note = "담당자가 당사자에게 직접 묻는 말" if consultation else "국민이 실제로 물을 법한 말투의 질문"
    answer_note = "현장에서 확인·기록할 항목" if consultation else "답변 방향 한두 문장(사실을 지어내지 말고 무엇을 설명·확인해야 하는지 쓴다)"
    return f"""정책: {title}
아래는 합성 인물 반응에서 나온 쟁점이다. 한 줄 형식은 id|쟁점|요약이다.
{issue_lines}

{task}
· question: {question_note}
· answer: {answer_note}
· issue_id: 관련 쟁점 id
JSON 형식: {{"items": [{{"question": "...", "answer": "...", "issue_id": "i1"}}]}}"""


def amend_prompt(title: str, policy_text: str, segment_lines: str, suggestion_lines: str) -> str:
    return f"""정책: {title}
[정책]
{policy_text}
[/정책]

조항 목록(id|조항):
{segment_lines}

합성 인물들이 남긴 보완 제안 묶음(id|묶음 이름|인원|예시 원문):
{suggestion_lines}

묶음마다 정책 원문 끝에 덧붙일 수정 문장을 하나씩 써라.
· text: "[수정안]"으로 시작하는 한두 문장. 누가, 무엇을, 어떻게 바뀌는지 드러낸다.
· 날짜·나이를 계산해야만 효과가 드러나는 표현은 피하고, 누가 어떤 영향을 받는지를 문장에 직접 쓴다.
  (예: "2031년부터 시행한다" 대신 "현재 65~69세는 계속 무임승차를 받는다")
· title: 12자 안팎의 이름
· segment: 이 수정이 고치는 조항 id. 없으면 null
· 제안에 없는 내용을 지어내지 않는다.

JSON 형식: {{"items": [{{"source": "c0", "title": "...", "text": "[수정안] ...", "segment": "s2"}}]}}"""
