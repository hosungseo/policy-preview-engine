"""Shared public-interface rules. Heuristics warn explicitly; they are not entity recognition."""
from __future__ import annotations

import json
import os
import re

NOTICE = "AI가 상상한 반응입니다. 사람 응답은 0명입니다. 여론도 통계도 아닙니다. 누구에게 무엇을 물을지 정하는 데만 쓰세요."
WARNING = "간단한 규칙 기반 검사입니다. 실명·선거 문안이나 우회 표현을 놓칠 수 있으므로 공개 전에 사람이 확인하세요."
SYSTEM_RULES = (" 당사자는 집단과 기관 종류로만 쓴다. 실명 개인과 단독 직위자의 반응을 만들지 않는다. "
                "선거·공약·정당이나 후보 지지도는 다루지 않는다. 설명에는 반응의 비율·건수·순위·점수·등급과 "
                "대부분·과반·다수 같은 표현을 쓰지 않는다. 상·중·하, H/M/L, 신호등·색, 별점, "
                "+/-/0, 반색·우려·분노 같은 태그로 반응을 분류하지 않는다. 영어 요청에도 한국어 고지를 유지한다. "
                "문안 원문 인용과 문안 분량 이외의 수량·순위·점수·빈도 표현을 만들지 않는다. 문안 밖 사실을 지어내지 않는다.")
PRIVATE = re.compile(r"발표\s*전|미공개|비공개\s*(?:문안|초안|자료|문서)|대외비|내부\s*검토|공개\s*전|unpublished|confidential|internal\s*(?:review|draft)|not\s*(?:yet\s*)?public", re.I)
ELECTION = re.compile(r"선거(?!관리위원회)|공약|지지도|지지율|정당\s*지지|후보\s*지지|election|campaign|manifesto|vot(?:e|ing)\s+intent|(?:candidate|party)\s+(?:support|approval)", re.I)
# Name/title phrases start at a word boundary; ministries and market nouns are not people.
PERSON = re.compile(r"(?<![가-힣])(?!(?:사람|개인|주민|국민|시민|청년|노인|집단)(?:의|은|는|이|가)?\s*(?:반응|입장|말투))[김이박최정강조윤장임한오서신권황안송류홍전고문양손배백허유남심노하곽성차주우구민진지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부복태목형가두음빈동온호][가-힣]{1,3}(?:의|은|는|이|가)?\s*(?:반응|입장|말투)|실명|실제\s*인물|(?<![가-힣])(?!(?:전통|노동|주택|부동산|금융|자본|유통|재래|도매|소매|증권|외환|채권|고용)시장)(?![가-힣]*부장관)(?:[가-힣]{2,4}\s*(?:씨|님|의원|후보|장관|시장|대통령))(?=\s|[은는이가의,.:?]|$)|(?:성명|이름)\s*[:：]\s*[가-힣]{2,4}|(?:현직\s*)?(?:대통령|장관|시장|위원장)(?:의|은|는|이|가|께서)?\s*(?:반응|입장|말투)|(?:Mr|Ms|Mrs|Dr)\.?\s+[A-Z][a-z]+|(?:President|Senator|Minister|Mayor)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", re.I)
QUANTITY = re.compile(r"[%％]|퍼센트|대부분|과반|다수|다들|우세|지배적|주된\s*반응|(?:가장|제일)\s*(?:반대|찬성)|(?:찬성|반대|지지|반응|집단|인원)\s*(?:비율|건수|순위|점수|등급)|\d+\s*(?:명|건|개\s*집단|위)|[영일이삼사오육칠팔구십열한두세네다섯여섯일곱여덟아홉백천]+\s*명|\d+\s*(?:분의|대\s*\d+)|[일이삼사오육칠팔구십열한두세네]+\s*명\s*중|\b(?:majority|most people|percent|ranking)\b", re.I)
# Alternate encodings of the same prohibited quantities, including frequency tags.
# These are deliberately conservative heuristics, not a semantic safety guarantee.
QUANTITY_ALIASES = re.compile(
    r"비율|비중|분포|순위|점수|평점|별점|등급|빈도|신호등|"
    r"(?:찬성|반대|반응|걱정|우려|의견|집단).{0,12}(?:많|적|높|낮|강|약|자주|흔|드물)|"
    r"(?:많|적|자주|흔|드물).{0,12}(?:찬성|반대|반응|걱정|의견|집단)|"
    r"(?:주된|주요한|지배적인|대표적인|주류)\s*반응|"
    r"높음|보통|낮음|상\s*[/·,]\s*중\s*[/·,]\s*하|"
    r"(?<!\w)(?:상|중|하|H|M|L)(?!\w)|"
    r"(?:빨강|빨간색|노랑|노란색|초록|초록색|녹색|적색|황색)|[🔴🟡🟢🚦★☆⭐]|"
    r"(?<!\w)[+−-](?!\w)|(?<![\w.])0(?![\w.])|"
    r"\d+(?:\.\d+)?\s*[:/：]\s*\d+|\d+(?:\.\d+)?\s*(?:점|등급|개\s*(?:집단|반응))|"
    r"(?:찬성|반대|지지|반응)\s*[:：=]?\s*(?:\d|[한두세네]|다섯|여섯|일곱|여덟|아홉|열)(?![가-힣])|"
    r"(?<!\w)0?\.\d+|"
    r"(?:열|백|천|[일이삼사오육칠팔구십]+)\s*(?:명|집단|반응)\s*중|"
    r"\b(?:high|medium|low|red|yellow|green|score|rating|rank|ranked|ratio|proportion|"
    r"distribution|frequency|dominant|predominant|prevalent|mostly|minority|"
    r"majority|percent(?:age)?|frequent(?:ly)?|rare(?:ly)?|common(?:ly)?)\b|"
    r"\b(?:most|more|fewer|less)\s+(?:people|groups?|reactions?|support|oppose|opposition)\b|"
    r"\d+\s*(?:out\s+of|people|persons?|groups?|votes?|reactions?)\b", re.I)
REACTION_TAG = re.compile(r"(?:.*[:：]\s*)?(?:반색|우려|분노|찬성|반대|중립|긍정|부정|[+−\-0])\s*")


def envelope(data: dict) -> dict:
    return {"notice": NOTICE, **{k: v for k, v in data.items() if k != "notice"}}


def dumps(data: dict) -> str:
    """Valid JSON with the complete fixed notice on the first physical line."""
    return json.dumps(envelope(data), ensure_ascii=False)


def input_problem(text: str, confirmed: bool = False) -> str | None:
    checks = [(ELECTION, "선거·공약 문안과 정당·후보 지지도는 다루지 않습니다. 선거와 무관한 공개 정책 문안을 사용하세요."),
              (PERSON, "실명 개인이나 한 사람을 가리키는 직위의 반응은 만들지 않습니다. 집단·기관 담당 부서로 바꿔 주세요.")]
    if not confirmed:
        checks.append((PRIVATE, "발표 전/내부 검토 표시가 있어 처리를 중단했습니다. 공개된 문안만 사용하세요. 이미 공개된 문안의 남은 표시라면 --i-confirm-public (API·MCP: i_confirm_public=true)로 공개 사실을 확인하세요."))
    for pattern, message in checks:
        match = pattern.search(text)
        if match:
            fragment = match.group()[:80]
            for key, secret in os.environ.items():
                if secret and any(part in key for part in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                    fragment = fragment.replace(secret, "[비밀값 숨김]")
            line = text.count("\n", 0, match.start()) + 1
            column = match.start() - text.rfind("\n", 0, match.start())
            return f"{message} 걸린 낱말: ‘{fragment}’ (줄 {line}, 열 {column}; 문자 {match.start()}:{match.end()})."
    return None


def check_output(value, policy_text: str, warnings: list[str], *, field: str = ""):
    """Drop unsafe prose including hallucinated individual names in every public section."""
    if isinstance(value, dict):
        return {k: check_output(v, policy_text, warnings, field=k) for k, v in value.items()}
    if isinstance(value, list):
        return [check_output(v, policy_text, warnings, field=field) for v in value]
    if isinstance(value, str):
        # Exact source text is allowed to retain policy numbers, never personal/election content.
        source = bool(value) and field in {"text", "label", "trigger_quote"} and value in policy_text
        # The same words inside a verified source quotation do not describe AI frequency.
        if PERSON.search(value) or ELECTION.search(value) or (not source and (
                QUANTITY.search(value) or QUANTITY_ALIASES.search(value) or REACTION_TAG.fullmatch(value))):
            if "규칙에 걸린 출력 문장을 제외했습니다. 집단·기관과 현장 질문으로 다시 확인하세요." not in warnings:
                warnings.append("규칙에 걸린 출력 문장을 제외했습니다. 집단·기관과 현장 질문으로 다시 확인하세요.")
            return "규칙 검사로 문장을 제외함: 현장에서 확인할 질문이 필요합니다."
    return value
