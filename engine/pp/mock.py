"""Deterministic fake answers per task, for tests and dry runs only.

Mock bundles are written to web/dev-runs and refused by the public export.
"""
from __future__ import annotations

import re

from . import config
from .llm import mock_handler, seed_of

_POLICY = re.compile(r"\[정책\]\n(.*?)\n\[/정책\]", re.DOTALL)
_RIDS = re.compile(r"^(r\d+)\|", re.MULTILINE)
_OCCUPATIONS = re.compile(r"^- (.+)$", re.MULTILINE)
_GROUPS = re.compile(r"^## 그룹: (.+)$", re.MULTILINE)
_ISSUES = re.compile(r"^(i\d+)\|", re.MULTILINE)


@mock_handler("target")
def _target(system: str, prompt: str) -> dict:
    return {"filters": [{"age_min": 60}], "keywords": ["지하철로"],
            "semantic_query": "지하철로 출퇴근하는 사람", "rationale": "MOCK"}


@mock_handler("react")
def _react(system: str, prompt: str) -> dict:
    s = seed_of(prompt)
    found = _POLICY.search(prompt)
    flat = " ".join((found.group(1) if found else "").split())
    start = s % max(1, len(flat) - 16)
    return {
        "support": s % 5 - 2,
        "impact": config.IMPACTS[s % 3],
        "trigger_quote": flat[start:start + 14],
        "reason": f"MOCK 반응 {s % 97}번입니다.",
        "concerns": [f"우려{s % 4}"],
        "hopes": [],
        "suggestion": f"MOCK 제안 {s % 3}" if s % 2 else "",
        "would_comment": s % 3 == 0,
        "channel": ["주민센터", "경로당", "유튜브"][s % 3],
    }


@mock_handler("cluster")
def _cluster(system: str, prompt: str) -> dict:
    ids = _RIDS.findall(prompt)
    k = 3 if len(ids) >= 3 else 1
    groups = [ids[i::k] for i in range(k)]
    return {"issues": [{"title": f"MOCK 쟁점 {i + 1}", "stance": config.STANCES[i % 3],
                        "summary": "MOCK 요약", "member_ids": g} for i, g in enumerate(groups) if g]}


_SOURCES = re.compile(r"^(c\d+)\|", re.MULTILINE)
_SEGMENTS = re.compile(r"^(s\d+)\|", re.MULTILINE)


@mock_handler("amend")
def _amend(system: str, prompt: str) -> dict:
    segs = _SEGMENTS.findall(prompt)
    return {"items": [{"source": c, "title": f"MOCK 수정안 {i + 1}", "text": f"[수정안] MOCK 수정 문장 {i + 1}.",
                       "segment": segs[i % len(segs)] if segs else None} for i, c in enumerate(_SOURCES.findall(prompt))]}


@mock_handler("occupation")
def _occupation(system: str, prompt: str) -> dict:
    return {"map": {o: config.OCCUPATION_MAJORS[seed_of(o) % 10] for o in _OCCUPATIONS.findall(prompt)}}


@mock_handler("outreach")
def _outreach(system: str, prompt: str) -> dict:
    return {"items": [{"group": g, "method": "MOCK 방문 간담회", "where": "MOCK 장소",
                       "when": "MOCK 시기", "why": "MOCK 이유"} for g in _GROUPS.findall(prompt)]}


@mock_handler("hearing")
def _hearing(system: str, prompt: str) -> dict:
    return {"text": f"MOCK 발언 {seed_of(prompt) % 1000}입니다. 제 생각은 이렇습니다."}


@mock_handler("hearing_summary")
def _hearing_summary(system: str, prompt: str) -> dict:
    return {"agreements": ["MOCK 합의"], "disagreements": ["MOCK 이견"], "missing": ["MOCK 추가 청취 대상"]}


@mock_handler("qa")
def _qa(system: str, prompt: str) -> dict:
    ids = _ISSUES.findall(prompt) or ["i1"]
    return {"items": [{"question": f"MOCK 질문 {n + 1}", "answer": "MOCK 답변 방향",
                       "issue_id": ids[n % len(ids)]} for n in range(3)]}
