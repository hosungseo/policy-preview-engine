"""Rule-based question checks, run before any model call (free, instant, explainable).

Each finding: {code, level: block|warn|info, message, hint}. Only `block` stops a run.
The rules look at the question and options only; the policy text is checked for personal data.
"""
from __future__ import annotations

import re

from pp.diagnostics import question_reliability_findings

ELECTION = re.compile(r"정당|후보|지지도|지지율|선거|투표|당선|대선|총선|지방선거|국회의원 선거|재보궐")
RRN = re.compile(r"(?<!\d)\d{6}\s*-\s*[1-8]\d{6}(?!\d)")
PHONE = re.compile(r"(?<!\d)01[016789]\s*-?\s*\d{3,4}\s*-?\s*\d{4}(?!\d)")
DOUBLE = re.compile(r" 및 |그리고|뿐만 아니라|와 함께|과 함께|동시에")
LOADED = ["당연히", "반드시", "무분별한", "무분별하게", "특혜", "퍼주기", "세금 낭비", "혈세", "국민을 위한", "국민을 위해",
          "부담을 덜기 위한", "부담을 덜어 주는", "대다수", "많은 국민", "전문가들은", "전문가들이", "합리적인", "불합리한",
          "과도한", "획기적인", "꼭 필요한", "시급한", "포퓰리즘", "악용", "부당한", "공정한"]
PREMISE = re.compile(r"때문에|기 위해|기 위한|위하여|심각한 문제|문제가 되고 있는|논란이 되고 있는")
POSITIVE = re.compile(r"찬성|동의함|동의한다|^동의|좋다|좋음|필요하다|필요함|만족|그렇다|매우 그렇다|대체로 그렇다|지지")
NEGATIVE = re.compile(r"반대|동의하지 않|비동의|나쁘다|나쁨|필요 없|필요하지 않|불만족|그렇지 않|아니다")
NEUTRAL = re.compile(r"보통|중립|모르|잘 모르겠다|판단하기 어렵|무응답|그저 그렇")
DOUBLE_NEG = re.compile(r"않지 않|없지 않|아니지 않")
# Questions the synthetic panel cannot answer from data. Its income, assets and benefit flags are bands drawn from
# statistics, so a person's benefit amount, eligibility or ability to repay is a model guess dressed as a figure.
# Only forms addressed to the respondent ("받으실", "해당하십니까", "갚을 수 있") match; asking an opinion about who a
# policy covers ("70세 이상을 지원 대상에 포함하는 것") does not.
AMOUNT = re.compile(r"얼마(?:를|나|만큼)? ?(?:받(?!아들)|지원받|지급받|내야|부담하|갚)|금액(?:은|이|을|를) ?(?:얼마|받)|"
                    r"(?:수급|지원|신청|수혜) ?자격(?:이|을)? ?(?:있|되|갖추)(?:으십|으세요|으신|나요|는지|습니까|십)|"
                    r"(?:지원|수급|수혜) ?대상(?:자)?(?:에|이|으로)? ?(?:해당(?:하|되)|되|선정되|포함되)(?:십|시|세요|나요|는지)|"
                    r"(?:상환|갚)(?:을|할|하실|으실) 수 있|대출(?:을|이)? ?받(?:을|으실) 수")
# Its digital line says whether the person finds information online (a survey proxy); it holds nothing about
# filing papers or applying in an app, which a test scenario must state itself. "신청할 수 있게 하는 것" (a policy
# design) does not match; "신청하실 수 있습니까" (the person's ability) does.
_ABLE = r"(?:하실 수 있|할 수 있(?:으십|습니까|나요|겠|을까)|할 줄 아|하기 어려우)"
PROCEDURE = re.compile(r"(?:앱|어플|애플리케이션|온라인|인터넷|누리집|홈페이지|모바일|정부24|전자) ?(?:으로|로|에서)? ?"
                       rf"(?:직접 )?(?:신청|제출|접수|발급|등록){_ABLE}|서류(?:를)? ?(?:직접 )?(?:제출|준비|발급){_ABLE}")


def _f(code: str, level: str, message: str, hint: str = "") -> dict:
    return {"code": code, "level": level, "message": message, "hint": hint}


def check(policy_text: str, question: str, options: list[str]) -> list[dict]:
    q = (question or "").strip()
    opts = [o.strip() for o in options if o and o.strip()]
    found: list[dict] = []
    text = " ".join([q, *opts])
    if ELECTION.search(text):
        found.append(_f("election", "block", "선거·정당·후보·지지도에 관한 문항은 다룰 수 없습니다.",
                        "공직선거법 제86조 제1항 제3호는 공무원이 정당 또는 후보자에 대한 지지도를 조사하거나 발표하는 행위를 금지합니다."))
    if RRN.search(policy_text + text) or PHONE.search(policy_text + text):
        found.append(_f("personal", "block", "주민등록번호·휴대전화 번호로 보이는 내용이 있습니다. 지우고 다시 입력해 주세요."))
    hit = DOUBLE.search(q)
    if hit:
        found.append(_f("double", "warn", f"한 문항에서 두 가지를 함께 묻는 것 같습니다(‘{hit.group(0).strip()}’).",
                        "응답자가 둘 중 하나에만 찬성할 수 있습니다. 문항을 나누거나 하나만 물으세요."))
    loaded = [w for w in LOADED if w in q]
    if loaded:
        found.append(_f("loaded", "warn", f"응답을 한쪽으로 기울일 수 있는 표현이 있습니다: {', '.join('‘' + w + '’' for w in loaded)}.",
                        "평가가 담긴 말을 빼고 사실만 남기세요."))
    hit = PREMISE.search(q)
    if hit:
        found.append(_f("premise", "warn", f"문항이 이유나 목적을 전제로 깔고 있습니다(‘{hit.group(0)}’).",
                        "정책 내용만 묻고, 이유·목적은 정책 설명에 두세요."))
    if len(opts) < 2:
        found.append(_f("options_count", "block", "선택지를 2개 이상 넣어 주세요."))
    if len(opts) > 5:
        found.append(_f("options_count", "block", "선택지는 5개까지 넣을 수 있습니다."))
    if len(set(opts)) != len(opts):
        found.append(_f("options_overlap", "warn", "같은 선택지가 두 번 있습니다."))
    pos = [o for o in opts if POSITIVE.search(o) and not NEGATIVE.search(o)]
    neg = [o for o in opts if NEGATIVE.search(o)]
    if pos and neg and len(pos) != len(neg):
        found.append(_f("options_balance", "warn", f"긍정 선택지 {len(pos)}개와 부정 선택지 {len(neg)}개로 수가 다릅니다.",
                        "양쪽 단계 수를 맞추세요(예: 매우 찬성·찬성 / 반대·매우 반대)."))
    if opts and not any(NEUTRAL.search(o) for o in opts):
        found.append(_f("options_neutral", "info", "‘보통’이나 ‘잘 모르겠다’ 같은 선택지가 없습니다.",
                        "의견이 없는 사람이 억지로 한쪽을 고르게 됩니다."))
    if len(q) > 80:
        found.append(_f("long", "info", f"문항이 깁니다({len(q)}자). 80자 안쪽이 읽기 쉽습니다."))
    if DOUBLE_NEG.search(q):
        found.append(_f("double_negative", "warn", "이중 부정 표현이 있습니다. 긍정문으로 바꾸세요."))
    hit = AMOUNT.search(text)
    if hit:
        found.append(_f("amount_calc", "warn",
                        f"지원 금액·수급 자격·상환 능력을 묻는 것 같습니다(‘{hit.group(0).strip()}’). 합성 인물의 소득·자산·수급 "
                        "표시는 통계로 배정한 구간(가정)이라 이런 값을 계산하거나 판정할 수 없습니다.",
                        "찬반·걱정·기대처럼 태도를 묻고, 금액과 자격은 제도 기준으로 따로 확인하세요."))
    hit = PROCEDURE.search(text)
    if hit:
        found.append(_f("procedure_ability", "warn",
                        f"서류 제출·앱 신청 같은 절차 능력을 묻는 것 같습니다(‘{hit.group(0).strip()}’). 합성 인물에는 이 정보가 "
                        "없습니다. 디지털 항목은 ‘인터넷·스마트폰으로 필요한 정보를 찾을 수 있는지’ 설문의 대리값입니다.",
                        "절차 조건은 시험 조건으로 따로 정해 적고(예: ‘스마트폰 없음’), 나이로 채우지 마세요."))
    found.extend(question_reliability_findings(q, opts))
    return found


def blocked(findings: list[dict]) -> bool:
    return any(f["level"] == "block" for f in findings)
