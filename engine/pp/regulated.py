"""Whether a person lived in a regulated housing area (투기과열지구·조정대상지역) on a given date."""
from __future__ import annotations

import json
from pathlib import Path

LABELS = ("규제지역", "비규제 수도권", "지방", "일부(구분 불가)")
CAPITAL = ("서울", "인천", "경기")


def load(path: Path) -> list[dict]:
    periods = sorted(json.loads(Path(path).read_text(encoding="utf-8"))["periods"], key=lambda p: p["from"])
    for p in periods:
        if not p.get("source"):
            raise ValueError(f"regulated period {p['from']} has no source")
    return periods


def _in_force(periods: list[dict], date: str) -> dict | None:
    current = None
    for p in periods:
        if p["from"] <= date:
            current = p
    return current


def status(district: str, date: str, periods: list[dict]) -> str:
    """`district` is the persona DB value such as '경기-성남시 분당구'; an area 'X-*' covers every district of X."""
    p = _in_force(periods, date)
    if p:
        if district in p.get("partial", []):
            return "일부(구분 불가)"
        for area in p["areas"]:
            if area == district or (area.endswith("-*") and district.startswith(area[:-1])):
                return "규제지역"
    return "비규제 수도권" if district.split("-", 1)[0] in CAPITAL else "지방"


def unknown_areas(periods: list[dict], districts: set[str]) -> list[str]:
    names = {a for p in periods for a in [*p["areas"], *p.get("partial", [])] if not a.endswith("-*")}
    return sorted(names - districts)
