"""Question design in the Elephant-Goldfish way (google/elephant-goldfish-model), checked against data.

Elephant: one call reads the whole notice and drafts a few candidate questions, each tied to the passage it rests on.
Goldfish: every candidate is then reviewed by a separate call that sees only the notice text and that question - not the
drafting prompt or the other candidates - and first paraphrases what a reader would think is being asked, then lists
problems. The rule-based lint runs too.
Loop: a reviewer's rewrite becomes a new candidate and is read again by a fresh reviewer (one round).
Pilot: each candidate is asked to a small synthetic sample in both option orders ("don't know" kept last), measuring
order shift and undecided share (warnings) and one-sidedness (a note) - what the 2026-11-10 holdout experiment showed wording alone moves.
Candidates are ordered by these signals and one may be marked recommended; the person chooses.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from pp import config, llm, prompts
from pp.llm import mock_handler

from . import lint, panel
from .run import is_undecided, jev_questions, normalize, option_keys, state_for

MAX_CANDIDATES = 4
VERDICTS = ("좋음", "고쳐 쓰기", "쓰지 않기")
# Pilot flags (same thresholds as the result screen where they exist).
SHIFT_PP, UNDECIDED_PP, ONE_SIDED_PP = 7.0, 40.0, 90.0
ISSUE_KINDS = ("유도", "이중", "어려운 말", "원문에 없는 내용", "판단 불가", "선택지 불균형")

DRAFT_SYSTEM = "당신은 정부 의견조사 문항 설계자입니다. JSON 객체 하나로만 답하세요."
REVIEW_SYSTEM = ("당신은 설문 문항 검토자입니다. 이 문항이 어떻게 만들어졌는지 모르는 상태로, 정책 문안과 문항만 보고 "
                 "검토합니다. JSON 객체 하나로만 답하세요.")


def draft_prompt(title: str, text: str) -> str:
    return (f"[정책 제목] {title}\n[정책 문안]\n{text}\n[/정책 문안]\n\n"
            f"이 문안을 한 번 읽은 일반 국민에게 물을 객관식 문항 후보 {MAX_CANDIDATES}개를 만드세요.\n"
            "- 1개는 개정안 전체에 대한 찬반\n"
            "- 2개는 문안의 핵심 내용 하나씩에 대한 찬반(그 내용을 중립적인 한 구절로 문항에 넣기)\n"
            "- 1개는 이 변화가 응답자 생활에 미칠 영향\n"
            "규칙: 한 문항에 하나만 묻기. 답을 한쪽으로 미는 표현·감정 표현 금지. 문안에 없는 내용 넣지 않기. "
            "전문용어는 쉬운 말로. 문항은 80자 이내. 선택지는 3~5개, 긍정·부정이 균형을 이루고 '잘 모르겠다'를 넣을 수 있음.\n"
            '형식: {"candidates":[{"focus":"무엇을 묻는지 15자 이내","question":"…","options":["…"],'
            '"basis":"근거가 된 문안 구절을 그대로 옮긴 한 문장 이내"}]}')


def review_prompt(text: str, question: str, options: list[str]) -> str:
    kinds = ", ".join(ISSUE_KINDS)
    return (f"[정책 문안]\n{text}\n[/정책 문안]\n\n[문항] {question}\n[선택지] {' / '.join(options)}\n\n"
            "1) paraphrase: 이 문안을 한 번 읽은 보통 국민이 이 문항을 무엇을 묻는 것으로 이해할지 한 문장으로 쓰세요.\n"
            f"2) issues: 해당하는 문제를 하나에 한 줄씩 쓰세요. kind는 {kinds} 중 하나. 문제가 없으면 빈 배열.\n"
            f"3) verdict: {', '.join(VERDICTS)} 중 하나.\n"
            "4) better: verdict가 '좋음'이 아니면 고친 문항 한 줄(선택지 번호 없이 문항만), '좋음'이면 빈 문자열.\n"
            "5) better_options: 선택지도 바꿔야 하면 고친 선택지 목록, 아니면 빈 배열.\n"
            '형식: {"paraphrase":"…","issues":[{"kind":"…","message":"…"}],"verdict":"…","better":"…","better_options":[]}')


def _clean_options(options) -> list[str]:
    out = [str(o).strip()[:40] for o in (options or []) if str(o).strip()]
    return out[:5]


def _validate_draft(data: dict) -> dict:
    items = data["candidates"]
    if not isinstance(items, list) or not items:
        raise ValueError("no candidates")
    return data


def _validate_review(data: dict) -> dict:
    if data.get("verdict") not in VERDICTS or not str(data.get("paraphrase", "")).strip():
        raise ValueError("bad review")
    return data


def draft(title: str, text: str) -> list[dict]:
    """Elephant: candidate questions with the passage each rests on (kept only if it is really in the text)."""
    out = llm.complete_json("question_draft", DRAFT_SYSTEM, draft_prompt(title, prompts.clip(text, 6000)),
                            model=config.SYNTH_MODEL, validate=_validate_draft)
    flat = " ".join(text.split())
    candidates = []
    for c in out["candidates"]:
        question, options = str(c.get("question", "")).strip()[:200], _clean_options(c.get("options"))
        if not question or len(options) < 2:
            continue
        basis = " ".join(str(c.get("basis", "")).split())
        candidates.append({"focus": str(c.get("focus", "")).strip()[:30], "question": question, "options": options,
                           "basis": basis if basis and basis in flat else ""})
    return candidates[:MAX_CANDIDATES]


def review(text: str, question: str, options: list[str]) -> dict:
    """Goldfish: a fresh call with only the notice and this one question."""
    out = llm.complete_json("question_review", REVIEW_SYSTEM, review_prompt(prompts.clip(text, 6000), question, options),
                            model=config.SYNTH_MODEL, validate=_validate_review)
    issues = [{"kind": str(i.get("kind", "")).strip(), "message": str(i.get("message", "")).strip()}
              for i in out.get("issues") or [] if isinstance(i, dict) and str(i.get("message", "")).strip()]
    return {"paraphrase": str(out["paraphrase"]).strip(), "issues": issues, "verdict": out["verdict"],
            "better": str(out.get("better") or "").strip()[:200], "better_options": _clean_options(out.get("better_options"))}


def pilot(title: str, text: str, question: str, options: list[str], evaluate: Callable, n: int = 40,
          workers: int = 4, seed: int = 11) -> dict:
    """Ask the candidate to a small stratified synthetic sample in both orders and report the warning signs."""
    people = panel.sample(panel.load(addons="off")[0], n, seed)
    spec = {"title": title, "policy_text": text, "question": question}
    keys = option_keys(options)
    qs = {False: jev_questions(options), True: jev_questions(options, reverse=True)}

    def ask(task):
        reverse, person = task
        try:
            out = evaluate(state_for("main", spec, person), qs[reverse], cache=True, label="design")
            return reverse, normalize(out["answers"]["q"]["probabilities"], keys)
        except Exception:  # a failed pilot answer is left out; the count shows how many came back
            return reverse, None

    with ThreadPoolExecutor(max(1, workers)) as ex:
        rows = list(ex.map(ask, [(r, p) for p in people for r in (False, True)]))
    arms = {r: [v for rr, v in rows if rr == r and v] for r in (False, True)}
    if not arms[False] or not arms[True]:
        return {"n": 0, "flags": ["사전 시험 응답을 받지 못했습니다"]}
    mean = {r: [100 * sum(v[i] for v in arms[r]) / len(arms[r]) for i in range(len(keys))] for r in arms}
    both = [(a + b) / 2 for a, b in zip(mean[False], mean[True])]
    shift = max(abs(a - b) for a, b in zip(mean[False], mean[True]))
    undecided = sum(p for p, o in zip(both, options) if is_undecided(o))
    decided = [(p, o) for p, o in zip(both, options) if not is_undecided(o)]
    top = max(p for p, _ in decided) / max(1e-9, sum(p for p, _ in decided)) * 100 if decided else 0.0
    flags, notes = [], []
    if shift > SHIFT_PP:
        flags.append(f"선택지 순서만 바꿔도 {shift:.0f}%p 움직임")
    if undecided > UNDECIDED_PP:
        flags.append(f"‘모름’ {undecided:.0f}% — 응답자가 판단할 근거가 부족할 수 있음")
    if top > ONE_SIDED_PP:
        # Near-unanimity can be a real opinion (e.g. banning hidden cameras), so it is a note, not a defect.
        notes.append(f"의견을 낸 사람의 {top:.0f}%가 한쪽 — 실제로 이견이 적은 사안인지, 묻는 방식이 한쪽을 미는지 확인")
    return {"n": min(len(arms[False]), len(arms[True])), "percent": [round(p) for p in both],
            "shift_pp": round(shift, 1), "undecided_pp": round(undecided, 1), "one_sided_pp": round(top, 1), "flags": flags,
            "notes": notes}


def _rank(c: dict) -> tuple:
    verdict = (c.get("review") or {}).get("verdict")
    order = {"좋음": 0, "고쳐 쓰기": 1, None: 2, "쓰지 않기": 3}.get(verdict, 2)
    flags = len((c.get("pilot") or {}).get("flags", [])) if c.get("pilot") else 1
    blocks = sum(1 for f in c.get("lint", []) if f["level"] == "block")
    return (blocks, order, flags)


def propose(title: str, text: str, evaluate: Callable | None = None, pilot_n: int = 40, workers: int = 4) -> dict:
    candidates = draft(title, text)

    def check(c: dict) -> dict:
        try:
            gold = review(text, c["question"], c["options"])
        except llm.LLMError:
            gold = None  # a reviewer that failed did not review; never shown as "no problems"
        tested = pilot(title, text, c["question"], c["options"], evaluate, pilot_n) if evaluate and pilot_n else None
        return {**c, "review": gold, "pilot": tested, "lint": lint.check(text, c["question"], c["options"])}

    with ThreadPoolExecutor(max(1, min(workers, len(candidates) or 1))) as ex:
        reviewed = list(ex.map(check, candidates))
    # One EGM loop: a reviewer's rewrite becomes a candidate of its own and meets a fresh reviewer and the pilot.
    rewrites = []
    for c in reviewed:
        r = c.get("review") or {}
        if r.get("verdict") != "좋음" and r.get("better") and r["better"] != c["question"]:
            rewrites.append({"focus": f"{c['focus']} · 검토자 수정안"[:30], "question": r["better"],
                             "options": r.get("better_options") or c["options"], "basis": c["basis"], "revised_from": c["question"]})
    if rewrites:
        with ThreadPoolExecutor(max(1, min(workers, len(rewrites)))) as ex:
            reviewed += list(ex.map(check, rewrites))
    reviewed.sort(key=_rank)
    best = reviewed[0] if reviewed else None
    if best and _rank(best) == (0, 0, 0):
        best["recommended"] = True
    return {"candidates": reviewed, "model": llm.model_label(config.SYNTH_MODEL), "pilot_n": pilot_n if evaluate else 0}


@mock_handler("question_draft")
def _mock_draft(system: str, prompt: str) -> dict:
    return {"candidates": [
        {"focus": "전체 찬반", "question": "이 개정안에 찬성하십니까?", "options": ["찬성", "반대", "잘 모르겠다"], "basis": ""},
        {"focus": "생활 영향", "question": "이 개정안이 시행되면 귀하의 생활에 영향이 있을 것이라고 보십니까?",
         "options": ["영향이 클 것이다", "조금 있을 것이다", "거의 없을 것이다", "잘 모르겠다"], "basis": ""},
    ]}


@mock_handler("question_review")
def _mock_review(system: str, prompt: str) -> dict:
    return {"paraphrase": "MOCK 개정안에 대한 생각을 묻는 문항으로 이해합니다.", "issues": [], "verdict": "좋음", "better": ""}
