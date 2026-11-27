"""Jev question sets for a policy series: the measure questions (same wording as the case pipeline, so values
stay comparable) plus four housing questions, and the one-off tenure question."""
from __future__ import annotations

import re

from . import segment
from .jev_panel import POSITION_LEVELS, STANCE_LEVELS

# key -> (Korean label, English instruction)
HOUSING = {
    "h_stable": ("집값 안정 효과 기대", "This person believes this measure will help stabilize housing prices."),
    "h_home": ("내 집 마련·주거 안정에 도움", "This measure helps this person buy a home or keep their housing stable."),
    "h_harm": ("나에게 불리함", "This measure puts this person at a disadvantage."),
    "h_trust": ("정부 부동산 정책 신뢰", "This person trusts the government's housing policy."),
}
TENURE = {
    "own": ("자가", "Owns the home they live in"),
    "jeonse": ("전세", "Rents on a lump-sum deposit lease (jeonse)"),
    "monthly": ("월세", "Pays monthly rent, with or without a deposit"),
    "other": ("기타", "Lives rent-free, in company or official housing, a dormitory, or similar"),
}
MAX_SEGMENTS = 8
LABEL_MAX = 40
_BULLET = re.compile(r"(?m)^[ \t]*□")
# Leading item markers of Korean press releases: bullets, circled numbers, "(1)", "1.", "가."
_MARKER = re.compile(r"^(?:[□■▴▲○ㅇ◦▪•◈◇◆※\-–·①-⑳❶-❿➊-➓]|\(\d{1,2}\)|\d{1,2}\.(?=\s)|[가-하]\.(?=\s))\s*")


def _default_label(line: str) -> str:
    label = line.strip()
    while (m := _MARKER.match(label)) and m.end():
        label = label[m.end():]
    return label if len(label) <= LABEL_MAX else label[:LABEL_MAX - 1] + "…"


def _segments_at(text: str, marks: list[tuple[int, str]]) -> list[dict]:
    """Segments from (offset, label) marks; each runs to the next mark, without the excerpt's trailing '…' lines."""
    segs = []
    for k, (a, label) in enumerate(marks):
        b = marks[k + 1][0] if k + 1 < len(marks) else len(text)
        s = a + len(text[a:b]) - len(text[a:b].lstrip())
        body = text[s:b].rstrip()
        while body.endswith("\n…"):
            body = body[:-2].rstrip()
        segs.append({"id": f"s{k + 1}", "label": label, "text": body, "start": s, "end": s + len(body)})
    return segs


def _listed_segments(text: str, provisions: list) -> list[dict]:
    lines = text.split("\n")
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    marks, at = [], 0
    for p in provisions:
        start, label = (p, None) if isinstance(p, str) else (p["start"], p.get("label"))
        i = next((k for k in range(at, len(lines)) if lines[k].lstrip().startswith(start)), None)
        if i is None:
            raise ValueError(f"provision start not found at the start of a line: {start!r}")
        if label is not None and label not in text:
            raise ValueError(f"provision label is not verbatim in the text: {label!r}")
        marks.append((offsets[i], label or _default_label(lines[i])))
        at = i + 1
    return _segments_at(text, marks)


def measure_segments(text: str, provisions: list | None = None) -> list[dict]:
    """Provisions of a press-release excerpt.

    `provisions` lists, in order, the verbatim start of each provision's line, either as a string or as
    {"start": ..., "label": verbatim substring}. Without it the excerpt's own top-level '□' bullets are
    used, and numbered headings after that."""
    if provisions:
        segs = _listed_segments(text, provisions)
    else:
        starts = [m.start() for m in _BULLET.finditer(text)]
        if len(starts) >= 2:
            segs = _segments_at(text, [(s, _default_label(text[s:].split("\n", 1)[0])) for s in starts])
        else:
            segs = segment.split_segments(text)
    if not 2 <= len(segs) <= MAX_SEGMENTS:
        raise ValueError(f"{len(segs)} provisions; an excerpt needs 2 to {MAX_SEGMENTS}")
    return segs


def measure_questions(segments: list[dict]) -> dict:
    q = {
        "stance": {"type": "score", "criteria": STANCE_LEVELS,
                   "instructions": "Given this person's own job, family and circumstances, how would they react to the policy?"},
        "direct": {"type": "noul", "instructions": "The policy directly changes this person's work, daily life or spending."},
    }
    for s in segments:
        q[f"seg_{s['id']}"] = {"type": "noul", "instructions": f"The provision “{s['label']}” directly affects this person."}
        q[f"pos_{s['id']}"] = {"type": "score", "criteria": POSITION_LEVELS,
                               "instructions": f"How would this person feel about the provision “{s['label']}”?"}
    for key, (_, text) in HOUSING.items():
        q[key] = {"type": "noul", "instructions": text}
    return q


def summarize_measure(answer: dict, segments: list[dict]) -> dict:
    a = answer["answers"]
    probs = [round(float(a["stance"]["probabilities"].get(str(i), 0.0)), 4) for i in range(5)]
    return {
        "stance": round(float(a["stance"]["score"]) - 2, 4),  # expected level mapped to -2..+2
        "stance_probs": probs,
        "favor": round(probs[3] + probs[4], 4),
        "reserve": round(probs[0] + probs[1] + probs[2], 4),
        "direct": round(float(a["direct"]["noul"]), 4),
        "segments": {s["id"]: round(float(a[f"seg_{s['id']}"]["noul"]), 4) for s in segments},
        "positions": {s["id"]: round(float(a[f"pos_{s['id']}"]["score"]) - 1, 4) for s in segments},
        "pos_oppose": {s["id"]: round(float(a[f"pos_{s['id']}"]["probabilities"].get("0", 0.0)), 4) for s in segments},
        "housing": {k: round(float(a[k]["noul"]), 4) for k in HOUSING},
    }


def tenure_question() -> dict:
    return {"tenure": {"type": "choice", "criteria": {k: en for k, (_, en) in TENURE.items()},
                       "instructions": "Which best describes how this person occupies the home they live in now?"}}


def summarize_tenure(answer: dict) -> dict:
    probs = answer["answers"]["tenure"]["probabilities"]
    total = sum(float(probs.get(k, 0.0)) for k in TENURE) or 1.0
    return {"tenure": {k: round(float(probs.get(k, 0.0)) / total, 4) for k in TENURE}}
