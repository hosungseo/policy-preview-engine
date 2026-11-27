"""Quantitative panel scored by Jev: calibrated stance, direct impact, clause impact,
participation and information channel for every person, plus occupation mapping."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config, jev, prompts

STANCE_LEVELS = ["Strongly opposes", "Somewhat opposes", "Neutral or undecided", "Somewhat supports", "Strongly supports"]
CHANNELS = {
    "community_center": "주민센터·행정복지센터 안내나 반상회",
    "senior_center": "경로당·노인복지관",
    "neighborhood_chat": "동네 단톡방·이웃 입소문",
    "online_community": "온라인 커뮤니티·카페",
    "news_youtube": "뉴스·유튜브·TV",
    "association": "직능단체·협회·조합",
    "union_workplace": "노동조합·직장 공지",
    "school_parents": "학교·학부모 모임",
    "religious": "종교 모임",
    "none": "이런 소식을 거의 접하지 않음",
}
MAJORS = config.OCCUPATION_MAJORS
POSITION_LEVELS = ["Opposes this provision", "Neutral or no opinion", "Supports this provision"]
# Control for the amendment test: appending a sentence that changes nothing shows how much the act of
# appending text moves Jev on its own, so each amendment can be reported net of it.
PLACEBO = {"id": "p0", "title": "대조(내용 변화 없음)",
           "text": "[수정안] 조문의 표현과 조 번호만 정리하며, 내용은 바꾸지 않는다."}
# Ways to hear from people: key -> (Korean label, English description used in the question)
METHODS = {
    "town_hall": ("주민센터 설명회·공청회(평일 저녁)", "an in-person briefing or public hearing at a community center on a weekday evening"),
    "local_visit": ("경로당·마을 모임 방문 청취", "officials visiting their senior center, village hall or neighborhood gathering to ask in person"),
    "text_survey": ("문자로 받는 짧은 온라인 설문", "a short online survey link sent by text message"),
    "phone": ("10분 전화 인터뷰", "a phone interview of about ten minutes"),
    "workplace": ("직장·노조·협회를 통한 간담회", "a meeting arranged through their workplace, union or trade association"),
    "portal": ("입법예고 누리집 의견 쓰기", "writing a comment on the government's online legislative notice page"),
}


def questions(segments: list[dict], issues: list[dict] | None = None, *, extended: bool = True) -> dict:
    """Every judgment asked of one person in one call. Extra questions cost input tokens only
    (output is free) and barely change latency, so the call carries all of them."""
    # English instructions (Jev's primary language); the state itself stays in Korean.
    q = {
        "stance": {"type": "score", "criteria": STANCE_LEVELS,
                   "instructions": "Given this person's own job, family and circumstances, how would they react to the policy?"},
        "direct": {"type": "noul", "instructions": "The policy directly changes this person's work, daily life or spending."},
        "comment": {"type": "noul", "instructions": (
            "This person would personally submit an opinion to the government's official consultation on this "
            "policy, such as an online comment on the draft or speaking at a public hearing.")},
        "channel": {"type": "choice", "criteria": CHANNELS,
                    "instructions": "Where would this person most likely hear about this policy or talk about it?"},
    }
    for s in segments:
        q[f"seg_{s['id']}"] = {"type": "noul", "instructions": f"The provision “{s['label']}” directly affects this person."}
    if extended:
        for s in segments:
            q[f"pos_{s['id']}"] = {"type": "score", "criteria": POSITION_LEVELS,
                                   "instructions": f"How would this person feel about the provision “{s['label']}”?"}
        for key, (_, text) in METHODS.items():
            q[f"m_{key}"] = {"type": "noul", "instructions": f"If invited, this person would actually take part in {text}."}
        if segments:
            q["explain"] = {"type": "choice", "criteria": {s["id"]: s["label"] for s in segments},
                            "instructions": "Which provision would this person most need explained before giving an opinion on the policy?"}
        q["understand"] = {"type": "noul",
                           "instructions": "From the policy text alone, this person would understand what it changes for them."}
    for k, it in enumerate(issues or []):
        q[f"iss_{k}"] = {"type": "noul",
                         "instructions": f"This person would raise this concern about the policy: {it['title']} — {it['summary']}"}
    return q


def summarize(answer: dict, segments: list[dict], n_issues: int = 0) -> dict:
    a = answer["answers"]
    stance = a["stance"]
    probs = [round(float(stance["probabilities"].get(str(i), 0.0)), 4) for i in range(5)]
    row = {
        "stance": round(float(stance["score"]) - 2, 4),  # expected level mapped to -2..+2
        "stance_probs": probs,
        "stance_conf": round(float(stance.get("confidence", 0.0)), 3),
        "reserve": round(probs[0] + probs[1] + probs[2], 4),  # probability of not supporting
        "direct": round(float(a["direct"]["noul"]), 4),
        "comment": round(float(a["comment"]["noul"]), 4),
        "channel": a["channel"]["choice"],
        "channel_probs": {k: round(float(v), 4) for k, v in a["channel"]["probabilities"].items()},
        "segments": {s["id"]: round(float(a[f"seg_{s['id']}"]["noul"]), 4) for s in segments},
    }
    if segments and f"pos_{segments[0]['id']}" in a:
        pos = {s["id"]: a[f"pos_{s['id']}"] for s in segments}
        row["positions"] = {sid: round(float(v["score"]) - 1, 4) for sid, v in pos.items()}  # -1 oppose .. +1 support
        row["pos_oppose"] = {sid: round(float(v["probabilities"].get("0", 0.0)), 4) for sid, v in pos.items()}
    methods = {k[2:]: round(float(v["noul"]), 4) for k, v in a.items() if k.startswith("m_")}
    if methods:
        row["methods"] = methods
    if "explain" in a:
        row["explain"] = {k: round(float(v), 4) for k, v in a["explain"]["probabilities"].items()}
    if "understand" in a:
        row["understand"] = round(float(a["understand"]["noul"]), 4)
    if n_issues:
        row["issues"] = {str(k): round(float(a[f"iss_{k}"]["noul"]), 4) for k in range(n_issues)}
    return row


def run_jev_panel(people: list[dict], policy_title: str, policy_text: str, segments: list[dict], out_path: Path,
                  *, issues: list[dict] | None = None, workers: int = 16) -> tuple[list[dict], list[dict]]:
    """Score every person with one Jev call each; appends to out_path (JSONL) and resumes."""
    done: dict[str, dict] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[row["uuid"]] = row
    todo = [p for p in people if p["uuid"] not in done]
    qs = questions(segments, issues)
    n_issues = len(issues or [])
    lock = threading.Lock()
    failures: list[dict] = []

    def one(person: dict) -> dict:
        state = {"policy": {"title": policy_title, "text": policy_text}, "person": prompts.persona_profile(person)}
        return {"uuid": person["uuid"], **summarize(jev.evaluate(state, qs, label="panel"), segments, n_issues)}

    with ThreadPoolExecutor(max_workers=workers) as pool, open(out_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(one, p): p for p in todo}
        for future in as_completed(futures):
            person = futures[future]
            try:
                row = future.result()
            except (jev.JevError, KeyError, ValueError) as e:
                failures.append({"uuid": person["uuid"], "error": str(e)[:300]})
                continue
            with lock:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[row["uuid"]] = row
    return [done[p["uuid"]] for p in people if p["uuid"] in done], failures


def map_occupations_jev(occupations: list[str], *, per_call: int = 40, workers: int = 8) -> dict[str, str]:
    """Free-text occupation -> KSCO major group with Choice questions, many per call."""
    unique = sorted(set(occupations))
    criteria = {m: None for m in MAJORS}
    state = ("한국표준직업분류(KSCO) 대분류: " + ", ".join(MAJORS)
             + ". 무직, 주부, 학생, 은퇴자는 '무직·기타'로 분류한다.")
    chunks = [unique[i:i + per_call] for i in range(0, len(unique), per_call)]

    def one(chunk: list[str]) -> dict[str, str]:
        qs = {f"o{i}": {"type": "choice", "criteria": criteria,
                        "instructions": f"Which KSCO major group does the occupation “{occ}” belong to?"}
              for i, occ in enumerate(chunk)}
        answers = jev.evaluate(state, qs, label="occupations")["answers"]
        return {occ: answers[f"o{i}"]["choice"] if answers[f"o{i}"]["choice"] in MAJORS else "무직·기타"
                for i, occ in enumerate(chunk)}

    mapping: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(one, chunks):
            mapping.update(part)
    return mapping


def _issue_criteria(issues: list[dict]) -> dict:
    criteria = {f"i{k}": f"{it['title']} — {it['summary']}" for k, it in enumerate(issues)}
    criteria["none"] = "None of the listed issues is the main point of this reaction"
    return criteria


def _ask_issue(r: dict, criteria: dict, label: str) -> dict[str, float]:
    """Probability of each option (issue keys and "none") for one reaction."""
    state = {"reaction": r["reason"], "concerns": r.get("concerns", [])}
    question = {"issue": {"type": "choice", "criteria": criteria,
                          "instructions": "Which listed issue does this reaction mainly raise?"}}
    answer = jev.evaluate(state, question, label=label)["answers"]["issue"]
    probs = {k: float(answer["probabilities"].get(k, 0.0)) for k in criteria}
    if answer.get("choice") in criteria and not any(probs.values()):
        probs[answer["choice"]] = 1.0
    return probs


def assign_issues(issues: list[dict], reactions: list[dict], *, threshold: float = 0.5,
                  workers: int = 8) -> tuple[list[dict], dict]:
    """Re-decide issue membership with one Jev Choice per reaction; keep members with p >= threshold.

    The LLM names and summarises the issues; Jev decides which reactions belong to which issue,
    so quotes shown under an issue actually raise it."""
    criteria = _issue_criteria(issues)

    def one(r: dict) -> tuple[str, str, float]:
        probs = _ask_issue(r, criteria, "assign")
        choice = max(probs, key=lambda k: probs[k])
        return r["rid"], choice, probs[choice]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        decided = list(pool.map(one, reactions))
    llm_of = {rid: k for k, it in enumerate(issues) for rid in it["member_ids"]}
    jev_of = {rid: int(choice[1:]) for rid, choice, p in decided if choice != "none" and p >= threshold}
    prob_of = {rid: p for rid, _, p in decided}
    members: dict[int, list[str]] = {k: [] for k in range(len(issues))}
    for rid, k in jev_of.items():
        members[k].append(rid)
    kept = []
    for k, issue in enumerate(issues):
        ranked = sorted(members[k], key=lambda rid: -prob_of[rid])
        if ranked:
            kept.append({**issue, "member_ids": ranked, "member_probs": {rid: round(prob_of[rid], 3) for rid in ranked}})
    both = [rid for rid in jev_of if rid in llm_of]
    stats = {
        "reactions": len(reactions), "llm_assigned": len(llm_of), "jev_assigned": len(jev_of), "both": len(both),
        "agreement": round(sum(llm_of[rid] == jev_of[rid] for rid in both) / len(both), 3) if both else None,
        "threshold": threshold,
    }
    return kept, stats


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if not sx or not sy:
        return None
    return round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), 3)


def check_consistency(reactions: list[dict], policy_title: str, *, threshold: float = 1.5,
                      workers: int = 8) -> dict:
    """Jev reads each LLM reason (without its label) and estimates the stance it expresses.
    Reasons whose estimate is `threshold` levels or more away from the LLM's own label are flagged."""
    question = {"stance": {"type": "score", "criteria": STANCE_LEVELS,
                           "instructions": "What stance toward the policy does this person's statement express?"}}

    def one(r: dict) -> tuple[dict, float]:
        state = {"policy": policy_title, "statement": r["reason"]}
        return r, float(jev.evaluate(state, question, label="consistency")["answers"]["stance"]["score"]) - 2

    with ThreadPoolExecutor(max_workers=workers) as pool:
        judged = list(pool.map(one, reactions))
    items = [{"rid": r["rid"], "llm": r["support"], "jev": round(v, 3), "diff": round(v - r["support"], 3)} for r, v in judged]
    flagged = sorted((it for it in items if abs(it["diff"]) >= threshold), key=lambda it: (-abs(it["diff"]), it["rid"]))
    return {
        "n": len(items), "flagged": len(flagged), "threshold": threshold,
        "mean_abs_diff": round(sum(abs(it["diff"]) for it in items) / len(items), 3) if items else None,
        "corr": _pearson([float(it["llm"]) for it in items], [it["jev"] for it in items]),
        "items": flagged[:30], "by_rid": {it["rid"]: it["jev"] for it in items},
    }


def score_variants(people: list[dict], policy_title: str, policy_text: str, variants: list[dict], out_path: Path,
                   *, workers: int = 12) -> tuple[list[dict], list[dict]]:
    """Paired amendment test: the same people are asked the stance question for the original text ("base")
    and for the text with each amendment appended. Appends to out_path (JSONL) and resumes."""
    done: dict[tuple[str, str], dict] = {}
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[(row["uuid"], row["variant"])] = row
    texts = {"base": policy_text, **{v["id"]: f"{policy_text}\n\n{v['text']}" for v in variants}}
    question = {"stance": questions([], extended=False)["stance"]}
    tasks = [(p, vid) for p in people for vid in texts if (p["uuid"], vid) not in done]
    lock = threading.Lock()
    failures: list[dict] = []

    def one(task: tuple[dict, str]) -> dict:
        person, vid = task
        state = {"policy": {"title": policy_title, "text": texts[vid]}, "person": prompts.persona_profile(person)}
        stance = jev.evaluate(state, question, label="alternatives")["answers"]["stance"]
        probs = [round(float(stance["probabilities"].get(str(i), 0.0)), 4) for i in range(5)]
        return {"uuid": person["uuid"], "variant": vid, "stance": round(float(stance["score"]) - 2, 4), "probs": probs}

    with ThreadPoolExecutor(max_workers=workers) as pool, open(out_path, "a", encoding="utf-8") as sink:
        futures = {pool.submit(one, t): t for t in tasks}
        for future in as_completed(futures):
            person, vid = futures[future]
            try:
                row = future.result()
            except (jev.JevError, KeyError, ValueError) as e:
                failures.append({"uuid": person["uuid"], "variant": vid, "error": str(e)[:300]})
                continue
            with lock:
                sink.write(json.dumps(row, ensure_ascii=False) + "\n")
                sink.flush()
                done[(row["uuid"], vid)] = row
    return [done[(p["uuid"], vid)] for p in people for vid in texts if (p["uuid"], vid) in done], failures


def score_questions(people: list[dict], policy_title: str, policy_text: str, qa: list[dict],
                    *, workers: int = 16) -> list[dict]:
    """For each person, the probability of wanting each prepared question answered (one call per person)."""
    question_set = {f"q{i}": {"type": "noul",
                              "instructions": f"Before accepting this policy, this person would want this question answered: “{q['question']}”"}
                    for i, q in enumerate(qa)}

    def one(person: dict) -> dict | None:
        state = {"policy": {"title": policy_title, "text": policy_text}, "person": prompts.persona_profile(person)}
        try:
            answers = jev.evaluate(state, question_set, label="questions")["answers"]
        except (jev.JevError, KeyError, ValueError):
            return None
        return {"uuid": person["uuid"], "asks": {str(i): round(float(answers[f"q{i}"]["noul"]), 4) for i in range(len(qa))}}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return [row for row in pool.map(one, people) if row]


def assign_issues_both_orders(issues: list[dict], reactions: list[dict], *, threshold: float = 0.5,
                              workers: int = 16) -> tuple[list[dict], dict]:
    """Issue membership asked with the options in their original and in reversed order, probabilities averaged.

    Reversing the list moved the probability of the same answer by as much as 0.49 -> 0.85 in a probe, which
    decides whether a reaction clears the threshold. Averaging both orders cancels that position effect.
    Each kept issue keeps its `k` (its position in the per-person Jev question set)."""
    criteria = _issue_criteria(issues)
    reversed_criteria = dict(reversed(list(criteria.items())))

    def one(r: dict) -> tuple[str, dict, dict]:
        return r["rid"], _ask_issue(r, criteria, "order"), _ask_issue(r, reversed_criteria, "order")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        decided = list(pool.map(one, reactions))
    members: dict[int, list[tuple[str, float]]] = {k: [] for k in range(len(issues))}
    same = flips = 0
    shifts = []
    for rid, orig, rev in decided:
        first = max(orig, key=lambda k: orig[k])
        second = max(rev, key=lambda k: rev[k])
        same += first == second
        shifts.append(abs(orig[first] - rev.get(first, 0.0)))
        avg = {k: (orig[k] + rev.get(k, 0.0)) / 2 for k in orig}
        pick = max(avg, key=lambda k: (avg[k], k == first))
        single = first if first != "none" and orig[first] >= threshold else None
        final = pick if pick != "none" and avg[pick] >= threshold else None
        flips += single != final
        if final:
            members[int(final[1:])].append((rid, avg[pick]))
    kept = []
    for k, issue in enumerate(issues):
        ranked = sorted(members[k], key=lambda m: (-m[1], m[0]))
        if ranked:
            kept.append({**issue, "k": issue.get("k", k), "member_ids": [rid for rid, _ in ranked],
                         "member_probs": {rid: round(p, 3) for rid, p in ranked}})
    n = len(reactions)
    stats = {"reactions": n, "same_choice": same, "agreement": round(same / n, 3) if n else None,
             "flips": flips, "assigned": sum(len(m) for m in members.values()),
             "mean_shift": round(sum(shifts) / n, 3) if n else None, "threshold": threshold}
    return kept, stats


# Plain-language problems a reader could have with one provision (probability that the problem exists).
CLARITY = {
    "jargon": ("어려운 용어", "The provision uses legal or administrative jargon that an ordinary adult would not understand."),
    "vague_who": ("대상 모호", "It is unclear exactly who this provision applies to."),
    "missing_detail": ("기준·숫자 누락", "The provision leaves out a concrete number, date, amount or criterion that a reader would "
                                     "need to know what happens to them."),
    "unclear_change": ("달라지는 점 불분명", "A reader cannot tell what changes compared with the current situation."),
    "delegated": ("하위 규정에 미룸", "Key details are left to later rules or decisions instead of being stated in this provision."),
    "ambiguous": ("두 가지로 읽힘", "The provision could reasonably be read in two different ways."),
    "hidden_burden": ("숨은 부담", "The provision creates a cost, duty or restriction for someone without saying so plainly."),
    "no_reason": ("이유 설명 없음", "The provision does not explain why it is needed."),
}
# What a consultation notice should tell readers (probability that the text does it).
DOC_CHECKS = {
    "how_to_comment": ("의견 제출 방법·기한", "The text tells readers how and by when they can submit their opinions."),
    "who_affected": ("영향받는 사람", "The text says plainly who will be affected."),
    "when": ("시행 시기", "The text says when the policy takes effect."),
    "cost": ("재정·비용 추계", "The text gives an estimate of the cost or budget."),
    "contact": ("문의처", "The text gives a contact point for questions."),
    "alternatives": ("검토한 대안", "The text mentions alternatives that were considered."),
}


def check_clarity(policy_title: str, policy_text: str, segments: list[dict], *, threshold: float = 0.5,
                  workers: int = 8) -> dict:
    """Score every provision against the plain-language problems in CLARITY (one call per provision) and the
    whole text against DOC_CHECKS (one call)."""
    clause_q = {f"c_{k}": {"type": "noul", "instructions": text} for k, (_, text) in CLARITY.items()}
    doc_q = {f"d_{k}": {"type": "noul", "instructions": text} for k, (_, text) in DOC_CHECKS.items()}

    def clause(seg: dict) -> dict:
        state = {"policy_title": policy_title, "full_text": prompts.clip(policy_text, 4000),
                 "provision": {"label": seg["label"], "text": seg.get("text", seg["label"])}}
        a = jev.evaluate(state, clause_q, label="clarity")["answers"]
        values = {k: round(float(a[f"c_{k}"]["noul"]), 4) for k in CLARITY}
        flags = sorted((k for k, v in values.items() if v >= threshold), key=lambda k: -values[k])
        return {"segment_id": seg["id"], "values": values, "flags": flags}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        clauses = list(pool.map(clause, segments))
    doc = jev.evaluate({"policy_title": policy_title, "text": prompts.clip(policy_text, 6000)}, doc_q,
                       label="clarity")["answers"]
    return {
        "indicators": [{"key": k, "label": label} for k, (label, _) in CLARITY.items()],
        "clauses": clauses,
        "document": [{"key": k, "label": label, "p": round(float(doc[f"d_{k}"]["noul"]), 4)}
                     for k, (label, _) in DOC_CHECKS.items()],
        "threshold": threshold,
    }


# Cross-cutting angles a reaction can take, tagged independently (a reaction can carry several).
LENSES = {
    "cost": ("생계·비용 부담", "The reaction worries about money: higher costs, lost benefits or financial strain."),
    "fairness": ("형평성·차별", "The reaction says the policy is unfair to some group or treats people unequally."),
    "info": ("정보 부족·설명 요구", "The reaction says the person does not understand the policy well or wants more explanation."),
    "admin": ("절차·행정 부담", "The reaction worries about paperwork, procedures or administrative hassle."),
    "effect": ("실효성 의문", "The reaction doubts that the policy will actually work or be carried out as intended."),
    "safety": ("안전·위험", "The reaction is about safety, accidents or physical risk."),
    "region": ("지역 격차", "The reaction is about differences between regions, such as cities versus rural areas."),
    "generation": ("세대 문제", "The reaction is about differences or conflict between generations."),
    "welcome": ("기대·환영", "The reaction welcomes the policy or expects a personal or social benefit from it."),
    "distant": ("무관심·거리감", "The reaction says the policy has little to do with the person."),
    "trust": ("정부 신뢰", "The reaction expresses distrust of government or doubts its promises."),
    "proposal": ("보완 제안", "The reaction proposes a specific change or addition to the policy."),
}


def tag_reactions(reactions: list[dict], policy_title: str, *, workers: int = 16) -> dict[str, dict[str, float]]:
    """Probability of every lens for every reaction (one call per reaction)."""
    questions_ = {f"l_{k}": {"type": "noul", "instructions": text} for k, (_, text) in LENSES.items()}

    def one(r: dict) -> tuple[str, dict]:
        state = {"policy": policy_title, "reaction": r["reason"], "concerns": r.get("concerns", []),
                 "hopes": r.get("hopes", [])}
        a = jev.evaluate(state, questions_, label="lenses")["answers"]
        return r["rid"], {k: round(float(a[f"l_{k}"]["noul"]), 4) for k in LENSES}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(one, reactions))


def _diffs(a: list[float], b: list[float]) -> dict:
    d = [abs(x - y) for x, y in zip(a, b)]
    return {"mean_abs_diff": round(sum(d) / len(d), 4) if d else None, "max_abs_diff": round(max(d), 4) if d else None,
            "corr": _pearson(a, b)}


def check_batching(people: list[dict], policy_title: str, policy_text: str, batched: dict[str, dict], *,
                   workers: int = 16) -> dict:
    """Stance asked alone vs the same stance inside the full per-person question set."""
    question = {"stance": questions([], extended=False)["stance"]}

    def one(person: dict) -> float:
        state = {"policy": {"title": policy_title, "text": policy_text}, "person": prompts.persona_profile(person)}
        return float(jev.evaluate(state, question, label="batching")["answers"]["stance"]["score"]) - 2

    with ThreadPoolExecutor(max_workers=workers) as pool:
        alone = list(pool.map(one, people))
    return {"n": len(people), **_diffs(alone, [batched[p["uuid"]]["stance"] for p in people])}


def check_repeat(people: list[dict], policy_title: str, policy_text: str, segments: list[dict], issues: list[dict],
                 batched: dict[str, dict], *, workers: int = 16) -> dict:
    """The same full per-person call sent again, bypassing the cache, compared with the stored answer."""
    qs = questions(segments, issues)

    def one(person: dict) -> dict:
        state = {"policy": {"title": policy_title, "text": policy_text}, "person": prompts.persona_profile(person)}
        return summarize(jev.evaluate(state, qs, label="repeat", cache=False), segments, len(issues))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        again = list(pool.map(one, people))
    first = [batched[p["uuid"]] for p in people]
    stance = _diffs([a["stance"] for a in again], [f["stance"] for f in first])
    direct = _diffs([a["direct"] for a in again], [f["direct"] for f in first])
    n = len(people)
    return {"n": n, "stance_mean_abs_diff": stance["mean_abs_diff"], "stance_max_abs_diff": stance["max_abs_diff"],
            "direct_mean_abs_diff": direct["mean_abs_diff"],
            "channel_same": round(sum(a["channel"] == f["channel"] for a, f in zip(again, first)) / n, 3) if n else None}


# What each hearing speech does, read by Jev (probability).
TURN_MARKS = {
    "rebut": ("반박", "This speech disputes a point another participant made."),
    "new_point": ("새 논점", "This speech raises a point that has not come up in the discussion so far."),
    # narrow on purpose: "acknowledges a merit of the other side" fired on 35 of 36 polite speeches
    "concede": ("입장 완화", "The speaker explicitly changes, softens or takes back a position they themselves stated earlier "
                          "in this discussion."),
    "proposal": ("구체적 제안", "The speaker proposes a concrete change, condition or compromise."),
}


def read_hearing(policy_title: str, agenda: list[str], turns: list[dict], people: dict[str, dict], *,
                 workers: int = 8) -> list[dict]:
    """Jev reads every participant's speech in the (LLM-written) virtual hearing: the stance it expresses
    and what the speech does, given the discussion before it."""
    stance_q = {"stance": {"type": "score", "criteria": STANCE_LEVELS,
                           "instructions": "What stance toward the policy does the speaker express in this speech?"}}
    marks_q = {f"m_{k}": {"type": "noul", "instructions": text} for k, (_, text) in TURN_MARKS.items()}

    def label_of(uuid: str) -> str:
        p = people[uuid]
        return f"{p.get('name') or '참석자'}({p['age']}세·{p['occupation']})"

    jobs = []
    for i, t in enumerate(turns):
        if t["speaker"] == "사회자":
            continue
        before = "\n".join(f"{'사회자' if x['speaker'] == '사회자' else label_of(x['speaker'])}: {x['text']}" for x in turns[:i])
        jobs.append((i, t, before[-3000:]))

    def one(job: tuple[int, dict, str]) -> dict:
        i, t, before = job
        state = {"policy": policy_title, "agenda": agenda, "discussion_so_far": before,
                 "speaker": label_of(t["speaker"]), "speech": t["text"]}
        a = jev.evaluate(state, {**stance_q, **marks_q}, label="debrief")["answers"]
        return {"index": i, "round": t["round"], "speaker": t["speaker"],
                "stance": round(float(a["stance"]["score"]) - 2, 4),
                "marks": {k: round(float(a[f"m_{k}"]["noul"]), 4) for k in TURN_MARKS}}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, jobs))
