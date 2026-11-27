"""Optional output safety gate for the HTTP API and MCP tools (off by default).

``PP_SAFETY_GATE`` selects the mode:

* ``off`` (default, also when unset): responses are returned exactly as before.
* ``report``: responses are unchanged except for an added ``safety_gate`` section listing findings.
* ``block``: lines with findings are replaced by a withheld notice and the ``safety_gate`` section is added.

Four Korean rules run in-process with no extra dependencies:

* ``real_opinion``: synthetic answers presented as real public opinion or survey results.
* ``eligibility``: definite statements that someone does or does not qualify for a benefit.
* ``personal_history``: first-person or persona-attributed sensitive life events that no profile supports.
* ``prompt_injection``: instructions aimed at the AI assistant, role/special tokens, secret requests,
  hidden control characters or rendering tricks that ride along in reflected text.

These are conservative pattern rules, not a semantic guarantee. ``PP_SAFETY_GATE_URL`` may also name a local
NeMo Guardrails server (loopback only); its ``/v1/checks`` check mode then reviews the same content text, for
example with Nemotron Content Safety and NemoGuard JailbreakDetect (see experiments/safety). A failing or
unreachable external check is reported; in ``block`` mode it withholds the content (fail closed).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import unicodedata
import urllib.parse
from dataclasses import dataclass

MODES = ("off", "report", "block")
RULES = {
    "real_opinion": "실제 여론으로 오인할 표현",
    "eligibility": "수급 자격 단정",
    "personal_history": "프로필에 없는 개인사",
    "prompt_injection": "프롬프트 주입",
}
WITHHELD = "안전 관문이 가린 문장입니다({label}). 원문 문안과 현장 확인으로 다시 보세요."
WITHHELD_ALL = "안전 관문 외부 검사({reason})로 내용을 가렸습니다. 원문 문안과 현장 확인으로 다시 보세요."
NOTE = "규칙 기반 출력 검사입니다. 놓치거나 지나치게 막을 수 있으므로 공개 전에 사람이 확인하세요."
# Marks verbatim policy lines in the text sent to the external check, so it can apply only injection checks there.
SOURCE_MARK = "[문안 인용] "

# Engine-owned copy at any depth: notices and recovery guidance that legitimately name tools and arguments.
_ENGINE_COPY_KEYS = frozenset({
    "notice", "trial_notice", "save_notice", "assistant_guidance", "result_label", "stage_label", "next_action",
    "free_alternative", "message", "error", "error_code", "code", "retryable", "scope", "source_notice",
    "input_warning", "safety_gate",
})
# Engine-owned metadata at the top or result level: receipts, settings and numbers rather than prose.
_METADATA_KEYS = frozenset({
    "warnings", "limits", "attribution", "selection", "budget", "estimate", "execution_inputs", "diagnostics",
    "conditions", "input_hash", "schema", "provenance", "id", "run_id", "plan_id", "status", "stage", "mode",
    "setup_warnings", "data", "panel", "keys", "outreach_notes", "credit", "archive",
})
# Verbatim policy or notice text that the engine already verified or fetched: rules about how the AI
# describes people do not apply to the source itself, but prompt-injection checks still do.
_SOURCE_KEYS = frozenset({"source_quote", "trigger_quote", "policy_text", "quote", "reaction_quotes"})
_SOURCE_PREFIXES = ("문안 근거(일부):", "보관 결과 인용:")

_NEG = re.compile(r"아(?:닙니다|니다|님|니며|니고|니에요|니라)|않(?:습니다|는다|음|으며|고)|대신하지|대체하지|"
                  r"단정하지|판단하지|보장하지|없는\s*것이|뜻하지")
_DIRECTIVE = re.compile(r"(?:에게|에서|께|와|과|으로|로)\s*(?:직접\s*)?(?:확인|물어|묻|들어|듣)|확인하세요|확인이\s*필요|"
                        r"확인할|확인해|물어보세요|물어\s*보|물을\s*질문|들어\s*보세요|[?？]\s*$|(?:나요|까요|는지|은지|인지)\s*[.?？]?\s*$")

_GAP = r"[^.?!。？！]{0,40}?"  # same sentence, lazily
_REAL_OPINION = [re.compile(p, re.I) for p in (
    r"(?<![가-힣])(?:국민|시민|주민|도민|구민|군민|지역)?\s*여론(?:은|이|을|도|상|으로|의)?(?!\s*조사를?\s*대신)",
    r"(?<![가-힣])민심|(?<![가-힣])민의(?=$|[은는이가를을도,.\s])|국민\s*(?:정서|뜻|목소리)(?:는|가|를|은)",
    r"(?:설문|여론\s*조사|실태\s*조사|조사)\s*결과",
    r"것으로\s*(?:나타났|조사됐|조사되었|집계|드러났|확인됐|확인되었)",
    r"(?:실제|현실의|진짜)\s*(?:국민|시민|주민|응답자|사람들|당사자|이용자|유권자)(?:들)?(?:은|는|이|가|도|의\s*(?:의견|반응|생각))",
    r"(?:응답자|응답한\s*(?:사람|국민|시민|주민))(?:들)?(?:의|은|는|이|가)?\s*(?:\d|대다수|다수|과반|절반|대부분|상당수)",
    r"(?:국민|시민|주민|도민|이용자|어르신|청년|노인|시민사회|농민|어민|상인|소상공인|자영업자|학부모|직장인|고령층|청년층|"
    r"노년층|장애인|당사자|근로자|노동자|임차인|세입자)(?:들)?(?:의)?\s*(?:대다수|과반|절반\s*이상|대부분|압도적\s*다수|상당수)",
    r"(?:국민|시민|주민|사람)들(?:은|이)\s*(?:실제로|이미|대체로|분명히)" + _GAP + r"(?:찬성|지지|환영|반대|반발)",
    r"(?:의견|여론)을?\s*(?:수렴|취합|모은|모아\s*본|들은)\S{0,2}\s*결과",
    r"\b(?:survey|poll(?:ing)?)\s+(?:results?|shows?|found)\b|\baccording\s+to\s+(?:our|the|a)\s+(?:survey|poll)\b|"
    r"\bthe\s+public\s+(?:clearly\s+|strongly\s+)?(?:supports?|opposes?|wants?|rejects?)\b|"
    r"\bmost\s+(?:citizens|residents|people|voters)\s+(?:support|oppose|want|reject)\b",
)]
_SUBJECT = r"(?:당신|귀하|이\s*분|이분|어르신(?:은|께서는|께서)|이\s*인물|해당\s*인물|이\s*사람|회원님|고객님|여러분|응답자)"
_BENEFIT = r"(?:수급|지원|급여|연금|수당|감면|혜택|보조금|바우처|대상|자격|차상위|기초생활)"
_VERDICT = (r"(?:입니다|이다|이에요|예요|에\s*해당(?:합니다|한다|됩니다|돼요)|[이가]\s*됩니다|[이가]\s*된다|이\s*있습니다|이\s*있다|"
            r"[을를]\s*충족(?:합니다|한다)?|[을를]?\s*받(?:을|으실|으신)\s*수\s*있(?:습니다|다|어요)|[을를]?\s*받(?:습니다|는다|게\s*됩니다)|"
            r"이\s*아닙니다|이\s*없습니다|에서\s*(?:제외|탈락)(?:됩니다|된다|합니다)|(?:에서|에)?\s*탈락(?:합니다|한다|입니다)|"
            r"(?:으로|로)\s*(?:판정|분류|선정|확정)(?:됩니다|된다|되었습니다|됐습니다)|이\s*확정(?:됩니다|된다))")
_ELIGIBILITY = [re.compile(p, re.I) for p in (
    _SUBJECT + _GAP + _BENEFIT + r"[^\s.?!。]{0,6}?\s*" + _VERDICT,
    r"(?:반드시|틀림없이|무조건|확실히|분명히|100\s*%|백\s*퍼센트)" + _GAP +
    r"(?:받(?:을|으실|습니다|는다|게)|지급(?:됩니다|된다|받)|대상(?:입니다|이다|이\s*됩니다)|해당(?:합니다|됩니다|한다)|자격(?:이|을))",
    r"(?:기초생활\s*수급자|차상위\s*계층|차상위|기초연금\s*수급자|수급권자|수급\s*대상자?)(?:로|으로)\s*(?:판정|분류|확정|선정)"
    r"(?:됩니다|된다|되었습니다|됐습니다|되어)",
    r"(?:지원|수급|급여|연금|수당)\s*(?:자격|대상)\S{0,2}\s*(?:이|을)?\s*(?:확정|보장)(?:됩니다|된다|입니다|합니다)",
    r"\b(?:is|are)\s+(?:definitely\s+|certainly\s+|surely\s+|clearly\s+)?(?:eligible|ineligible|not\s+eligible|entitled)\s+(?:for|to)\b",
)]
_FIRST_PERSON = re.compile(r"(?<![가-힣])(?:저는|제가|저도|저희|제\s|나는|내가|우리\s*(?:집|아들|딸|남편|아내|엄마|아빠|어머니|"
                           r"아버지|가족|아이|애|손주|부모님)|이\s*(?:인물|분|사람|응답자)(?:은|는|이|가)|해당\s*인물)")
# Short event words need a word start, so "사법부도" is not 부도 and "국민의" is not 민의.
_LIFE_EVENT = re.compile(r"사별|여의|돌아가셨|세상을\s*떠|이혼|별거|재혼|파산|개인회생|회생\s*신청|신용\s*불량|"
                         r"(?<![가-힣])(?:빚(?:이|을|만|더미)|채무|연체|체납|부도|전과|수감|출소|산재|중독|도박|노숙|입양)|"
                         r"대출(?:이|금|을)\s*\S{0,6}(?:갚|못|밀|연체)|실직|해고|권고사직|폐업|(?<![가-힣])암\s*(?:진단|수술|투병|환자)|"
                         r"투병|수술(?:을|을\s*받|했|받았)|입원(?:했|해|을|중)|장애\s*(?:판정|등급|진단)|치매\s*(?:진단|판정)|우울증|"
                         r"공황장애|교도소|유산(?:했|을\s*겪)|교통사고|산업재해|가정\s*폭력|학대(?:를|당)|자살\s*시도")
_EVENT_REACH = 40  # an event counts only in the same sentence and within this many characters of the speaker
_FIRST_PERSON_EN = re.compile(r"\b(?:I|my\s+(?:wife|husband|son|daughter|mother|father|family))\b")
_LIFE_EVENT_EN = re.compile(r"\b(?:lost\s+my\s+job|laid\s+off|divorc\w*|bankrupt\w*|widow\w*|cancer|surgery|prison|jail|"
                            r"disabilit\w*|addict\w*|evicted|died|passed\s+away)\b", re.I)
_INJECTION = [re.compile(p, re.I | re.M) for p in (
    r"(?:이전|앞|위|기존|모든|지금까지|앞서)\s*(?:의|에\s*받은|에\s*준)?\s*(?:지시|지침|명령|규칙|프롬프트|설정|안내|대화)\S{0,4}\s*"
    r"(?:은|는|을|를|다|모두|전부)?\s*(?:무시|잊어|잊고|따르지\s*말|취소|폐기|무효)",
    r"무시하고\s*(?:다음|아래|이것|이\s*지시|새로운)",
    r"(?:지금부터|이제부터|앞으로)\s*(?:너|당신|AI|비서|어시스턴트)(?:는|은|가)",
    r"(?:너|당신)(?:는|은)\s*이제(?:부터)?\s",
    r"역할(?:을|극)?\s*(?:바꿔|바꾸|맡아|연기해)|개발자\s*모드|관리자\s*모드|탈옥|제한(?:이|을)?\s*없는\s*(?:AI|모드|비서)",
    r"시스템\s*프롬프트|숨겨진\s*지시|내부\s*지시(?:문|사항)?\s*(?:을|를)\s*(?:보여|출력|알려)|system\s*prompt|hidden\s*instructions?",
    r"(?:API\s*키|키\s*값|비밀\s*키|토큰|비밀번호|패스워드|환경\s*변수|\.env|자격\s*증명|credential|secret)\S{0,4}\s*(?:을|를|도)?\s*"
    r"(?:출력|보여|알려|노출|보내|전송|붙여|적어|공개)",
    r"(?:사용자|유저|이용자)(?:에게|한테|께)?\s*(?:묻지|알리지|말하지|확인받지|보여주지)\s*(?:말고|않고)",
    r"(?<![\w.])(?:start_run|save_review|get_notice|find_notice|try_example|get_run|check_setup|estimate)\s*(?:\(|을|를)[^\n]{0,60}?"
    r"(?:호출|실행|부르)(?:하|해|하라|하세요|해라|해야)",
    r"i_confirm_public\s*[=:]|plan_id\s*[=:]",
    r"\bignore\s+(?:all\s+|any\s+)?(?:the\s+|your\s+)?(?:previous|prior|above|earlier|preceding)\b[^.\n]{0,40}?"
    r"\b(?:instructions?|prompts?|rules?|directions?)",
    r"\bignore\s+(?:them|this|that|it|everything|those)\s+and\s+(?:instead|just|only)\b",
    r"\bstop\s+everything\b|\bjust\s+(?:print|say|output|write|respond\s+with)\b|"
    r"\byou\s+(?:should|must|will)\s+(?:now\s+)?(?:only\s+)?(?:respond|reply|answer|print|say|output)\b",
    r"(?:라고|이라고)만\s*(?:출력|답|말|써)",
    r"\\(?:x1b|033|u001b|e)\[",
    r"\bdisregard\s+.{0,30}\b(?:instructions?|rules?|guidelines?)",
    r"\byou\s+are\s+now\b|\bact\s+as\s+(?:an?\s+)?(?:unrestricted|unfiltered|jailbroken)|\bdo\s+anything\s+now\b|\bDAN\b|\bjailbreak",
    r"\b(?:reveal|print|show|output|leak)\s+.{0,30}\b(?:system\s+prompt|instructions|api\s*key|secret|password|env(?:ironment)?\s+variables?)",
    r"<\|(?:im_start|im_end|system|user|assistant|endoftext|eot_id|start_header_id|end_header_id)\|>|\[/?INST\]|<</?SYS>>|"
    r"<(?:start|end)_of_turn>|</?(?:system|instruction)s?>",
    r"^\s*(?:system|assistant|developer|시스템|어시스턴트)\s*[:：]",
    r"^\s*#{2,}\s*(?:system|instructions?|시스템|지시(?:사항)?|새\s*지시)",
    r"!\[[^\]]*\]\(\s*(?:https?:)?//|<img\b[^>]*\bsrc\s*=|<script\b|javascript\s*:|<iframe\b",
)]
_HIDDEN = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]|\x1b\\[|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


class SafetyGateError(ValueError):
    pass


@dataclass(frozen=True)
class Finding:
    rule: str
    excerpt: str
    path: str = ""
    line: int = 0

    def public(self) -> dict:
        return {"rule": self.rule, "label": RULES[self.rule], "path": self.path, "line": self.line,
                "excerpt": self.excerpt}


def mode() -> str:
    raw = (os.environ.get("PP_SAFETY_GATE") or "").strip().lower()
    if not raw:
        return "off"
    if raw not in MODES:
        raise SafetyGateError(f"PP_SAFETY_GATE must be one of {', '.join(MODES)}")
    return raw


def _excerpt(text: str, start: int, end: int) -> str:
    left, right = max(0, start - 12), min(len(text), end + 12)
    visible = "".join(ch if unicodedata.category(ch)[0] != "C" or ch in "\t" else f"<U+{ord(ch):04X}>"
                      for ch in text[left:right])
    return ("…" if left else "") + visible[:120] + ("…" if right < len(text) else "")


_SENTENCE_END = re.compile(r"[.!?。？！]")


def _affirmed(line: str, match: re.Match) -> bool:
    """A match counts unless a negation follows it closely, or the rest of its sentence is a field-check
    directive or a question."""
    end = _SENTENCE_END.search(line, match.end())
    stop = end.end() if end else len(line)
    # The negation is looked for after the match, so a matched negative verdict ("대상이 아닙니다") still counts.
    near = line[match.end():min(match.end() + 30, stop)]
    return not (_NEG.search(near) or _DIRECTIVE.search(line[match.start():stop]))


def scan_text(text: str, *, profile: str | None = None, source: bool = False) -> list[Finding]:
    """Findings for one piece of text. ``source`` marks verbatim policy text (only injection rules apply).

    ``profile`` is the persona profile when the caller has it; life events it mentions are not findings.
    """
    if not text:
        return []
    findings: list[Finding] = []
    for lineno, line in enumerate(text.splitlines() or [text], 1):
        hidden = _HIDDEN.search(line)
        if hidden:
            findings.append(Finding("prompt_injection", _excerpt(line, hidden.start(), hidden.end()), line=lineno))
        else:
            for pattern in _INJECTION:
                m = pattern.search(line)
                if m:
                    findings.append(Finding("prompt_injection", _excerpt(line, m.start(), m.end()), line=lineno))
                    break
        if source:
            continue
        for rule, patterns in (("real_opinion", _REAL_OPINION), ("eligibility", _ELIGIBILITY)):
            for pattern in patterns:
                m = pattern.search(line)
                if m and _affirmed(line, m):
                    findings.append(Finding(rule, _excerpt(line, m.start(), m.end()), line=lineno))
                    break
        for person_re, event_re in ((_FIRST_PERSON, _LIFE_EVENT), (_FIRST_PERSON_EN, _LIFE_EVENT_EN)):
            person = person_re.search(line)
            if not person:
                continue
            end = _SENTENCE_END.search(line, person.end())
            stop = min(end.end() if end else len(line), person.end() + _EVENT_REACH)
            # Every event must be backed by the profile; one unsupported event is enough for a finding.
            unsupported = [e for e in event_re.finditer(line, person.start(), stop)
                           if not (profile and e.group().lower() in profile.lower())]
            if unsupported and not _DIRECTIVE.search(line[unsupported[0].start():]):
                findings.append(Finding("personal_history", _excerpt(line, person.start(), unsupported[0].end()),
                                        line=lineno))
                break
    return findings


def _engine_lines() -> tuple[str, ...]:
    from . import mcp_setup, public_rules, summary_card
    return tuple(s for s in (public_rules.NOTICE, public_rules.WARNING, mcp_setup.TRIAL_NOTICE, mcp_setup.TRIAL_LABEL,
                             summary_card.SAVE_NOTICE, NOTE) if s)


def _strip_prefix(line: str) -> tuple[str, bool]:
    body = line.strip().lstrip("•").strip()
    for prefix in _SOURCE_PREFIXES:
        if body.startswith(prefix):
            return body[len(prefix):].strip(), True
    return body, False


def _walk(value, path: str, key: str, out: list):
    if isinstance(value, dict):
        for k, v in value.items():
            if k in _ENGINE_COPY_KEYS or (k in _METADATA_KEYS and path.count(".") < 2):
                continue
            _walk(v, f"{path}.{k}" if path else k, k, out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk(v, f"{path}[{i}]", key, out)
    elif isinstance(value, str) and value.strip():
        out.append((path, key, value))


def _is_source(path: str, key: str) -> bool:
    return key in _SOURCE_KEYS or (key == "text" and "clauses" in path)


def _sources(strings) -> list[str]:
    texts = [value for path, key, value in strings if _is_source(path, key)]
    return [t.rstrip("…").strip() for t in texts if t.strip()]


def _loopback(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def external_check(text: str) -> dict | None:
    """Ask a local NeMo Guardrails server in check mode about ``text``; None when no server is configured."""
    url = (os.environ.get("PP_SAFETY_GATE_URL") or "").strip().rstrip("/")
    if not url:
        return None
    if not url.startswith(("http://", "https://")) or not _loopback(url):
        return {"status": "error", "reason": "PP_SAFETY_GATE_URL must be a loopback address"}
    from . import net
    # /v1/checks takes an OpenAI-style body, so "model" is required; check mode never calls a main model with it.
    body = {"model": "pp-safety-gate", "messages": [{"role": "assistant", "content": text}],
            "guardrails": {"rail_types": ["output"]}}
    config_id = (os.environ.get("PP_SAFETY_GATE_CONFIG") or "").strip()
    if config_id:
        body["guardrails"]["config_ids"] = [config_id]
    timeout = float(os.environ.get("PP_SAFETY_GATE_TIMEOUT") or 60)
    try:
        raw = net.post(url + "/v1/checks", json.dumps(body, ensure_ascii=False).encode("utf-8"),
                       headers={"Content-Type": "application/json"}, timeout=timeout)
        out = json.loads(raw)
    except Exception as exc:  # unreachable, timeout, HTTP error or bad JSON
        return {"status": "error", "reason": type(exc).__name__}
    status = str(out.get("status") or "error")
    return {"status": status, **({"rail": out["rail"]} if out.get("rail") else {}),
            **({"reason": str(out["reason"])[:200]} if out.get("reason") else {})}


def _replace(value, path: str, edits: dict):
    if isinstance(value, dict):
        return {k: _replace(v, f"{path}.{k}" if path else k, edits) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace(v, f"{path}[{i}]", edits) for i, v in enumerate(value)]
    if isinstance(value, str) and path in edits:
        return edits[path](value)
    return value


def apply(data: dict, *, profile: str | None = None) -> dict:
    """Gate one public response. In ``off`` mode the same object is returned untouched."""
    current = mode()
    if current == "off" or not isinstance(data, dict):
        return data
    engine = _engine_lines()
    strings: list = []
    _walk(data, "", "", strings)
    sources = _sources(strings)
    findings: list[Finding] = []
    flagged: dict[str, dict[int, str]] = {}
    content_lines: list[str] = []
    for path, key, value in strings:
        lines = value.splitlines() or [value]
        for lineno, line in enumerate(lines, 1):
            # Fixed engine copy is removed, not used to skip the line: reflected text may sit beside it.
            for fixed in engine:
                line = line.replace(fixed, " ")
            if not line.strip():
                continue
            body, quoted = _strip_prefix(line)
            is_source = _is_source(path, key) or quoted or any(body and body.rstrip("…") in s for s in sources)
            hits = scan_text(body, profile=profile, source=is_source)
            for hit in hits:
                findings.append(Finding(hit.rule, hit.excerpt, path, lineno))
                flagged.setdefault(path, {}).setdefault(lineno, RULES[hit.rule])
            content_lines.append(SOURCE_MARK + body if is_source else body)
    external = external_check("\n".join(dict.fromkeys(content_lines))) if content_lines else None
    external_blocked = bool(external) and external.get("status") in ("blocked", "error")
    # In block mode the excerpt would hand the withheld text straight back, so only rule and place are listed.
    listed = [f.public() if current == "report" else {k: v for k, v in f.public().items() if k != "excerpt"}
              for f in findings[:50]]
    summary = {"mode": current, "checked_strings": len(strings), "rules": list(RULES), "findings": listed,
               "finding_count": len(findings), "external": external, "note": NOTE}
    if current == "report":
        return {**data, "safety_gate": {**summary, "blocked": False}}
    if external_blocked:
        reason = external.get("rail") or external.get("reason") or external.get("status")

        def withhold(text: str) -> str:
            return "\n".join(line if line.strip() in engine else WITHHELD_ALL.format(reason=reason)
                             for line in text.splitlines() or [text])
        edits = {path: withhold for path, _, _ in strings}
    else:
        def redactor(lines_map):
            def run(text: str) -> str:
                lines = text.splitlines() or [text]
                return "\n".join(WITHHELD.format(label=lines_map[n]) if n in lines_map else line
                                 for n, line in enumerate(lines, 1))
            return run
        edits = {path: redactor(lines_map) for path, lines_map in flagged.items()}
    gated = _replace(data, "", edits) if edits else dict(data)
    gated["safety_gate"] = {**summary, "blocked": bool(edits)}
    return gated
