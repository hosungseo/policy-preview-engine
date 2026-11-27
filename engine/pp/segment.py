"""Split a policy text into addressable segments; locate verbatim quotes in it."""
from __future__ import annotations

import re

_HEADING = re.compile(r"(?m)^[ \t]*(?:\d{1,2}|[가-하])\.[ \t]+\S.*$")
MIN_BODY = 15
SHORT_LABEL = 20  # a heading this short with no body is a section title, not content
_TRANS = str.maketrans({"ㆍ": "·", "・": "·", "‧": "·", "“": '"', "”": '"', "‘": "'", "’": "'"})
_STRIP = " \"'「」『』.,…·:;"


def _short(label: str, limit: int = 48) -> str:
    return label if len(label) <= limit else label[: limit - 1] + "…"


def split_segments(text: str) -> list[dict]:
    """Segments start at line-leading '1.' or '가.' headings.

    A short heading with no body of its own (e.g. '2. 주요내용' directly
    followed by '가.') is a section title and is dropped; a one-line item such
    as '가. 기준 연령을 70세로 올린다.' is kept. Text before the first heading
    becomes '전문'.
    """
    heads = list(_HEADING.finditer(text))
    bounds: list[tuple[int, int, str]] = []
    first = heads[0].start() if heads else len(text)
    if text[:first].strip():
        bounds.append((0, first, "전문"))
    for i, match in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        bounds.append((match.start(), end, match.group(0).strip()))
    segments: list[dict] = []
    for start, end, label in bounds:
        chunk = text[start:end]
        own = len(chunk.strip()) - (0 if label == "전문" else len(label))
        if own < MIN_BODY and len(label) < SHORT_LABEL:
            continue
        s = start + (len(chunk) - len(chunk.lstrip()))
        e = end - (len(chunk) - len(chunk.rstrip()))
        segments.append({"id": f"s{len(segments) + 1}", "label": _short(label), "text": text[s:e], "start": s, "end": e})
    if not segments:
        s = len(text) - len(text.lstrip())
        e = len(text.rstrip())
        segments.append({"id": "s1", "label": "전문", "text": text[s:e], "start": s, "end": e})
    return segments


def _norm_map(text: str) -> tuple[str, list[int]]:
    """Whitespace-collapsed, variant-folded text plus a map back to original offsets."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text.translate(_TRANS)):
        if ch.isspace():
            if not chars or chars[-1] == " ":
                continue
            ch = " "
        chars.append(ch)
        index.append(i)
    return "".join(chars), index


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_TRANS)).strip()


def locate(quote: str, text: str) -> tuple[int, int] | None:
    q = normalize(quote or "").strip(_STRIP)
    if len(q) < 4:
        return None
    norm, index = _norm_map(text)
    pos = norm.find(q)
    if pos < 0:
        return None
    return index[pos], index[pos + len(q) - 1] + 1


def segment_of(offset: int, segments: list[dict]) -> str | None:
    for seg in segments:
        if seg["start"] <= offset < seg["end"]:
            return seg["id"]
    return None
