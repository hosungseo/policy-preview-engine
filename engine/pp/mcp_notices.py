"""Free legislative-notice discovery; model execution remains a separate explicit step."""
from __future__ import annotations

import re
from datetime import date

from . import lawmaking, public_rules, service
from .mcp_setup import SetupError


def _request_error() -> SetupError:
    return SetupError("invalid_notice_request")


def _read(call):
    try:
        return call()
    except lawmaking.LawmakingError as exc:
        # Upstream text can contain the API account; export only a local message.
        code = "notice_not_found" if exc.code == "not_found" else "lawmaking_unavailable"
        raise SetupError(code) from None
    except Exception:
        raise SetupError("lawmaking_unavailable") from None


def _period_dates(period: str) -> tuple[date, date] | None:
    dates = re.findall(r"(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", period)
    if len(dates) != 2:
        return None
    try:
        return tuple(date(*(int(part) for part in item)) for item in dates)
    except ValueError:
        return None


def find_notice(query: str = "", page: int = 1) -> dict:
    """Return only notices whose published comment period includes the local date."""
    if not isinstance(query, str) or (query.strip() and not 2 <= len(query.strip()) <= 50):
        raise _request_error()
    if type(page) is not int or not 1 <= page <= 50:
        raise _request_error()
    query = query.strip()
    found = _read(lambda: lawmaking.search(query, page) if query else lawmaking.recent(page=page))
    today = date.today()
    items = []
    unverified = False
    for row in found["items"]:
        period = _period_dates(row.get("period", ""))
        if period is None:
            unverified = True
        elif period[0] <= today <= period[1] and re.fullmatch(r"\d{1,10}", row.get("seq", "")):
            items.append(row)
    return public_rules.envelope({"items": items, "source": found["source"], "as_of": today.isoformat(),
        "page": found.get("page", page), "more": found.get("more", False), "total": None,
        "cost_usd": 0, "scope": "이번 검색 페이지에서 접수기간이 확인되고 오늘 의견을 받는 예고입니다.",
        "warnings": ["접수기간을 확인하지 못한 예고는 목록에서 제외했습니다."] if unverified else [],
        "next_action": "고른 항목의 seq와 API 메타정보가 있으면 함께 get_notice에 넣으세요." if items
                       else "다른 검색어나 다음 페이지로 찾아보세요. 무료 예시는 try_example으로 볼 수 있습니다."})


def get_notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "") -> dict:
    if not isinstance(seq, str) or not re.fullmatch(r"\d{1,10}", seq):
        raise _request_error()
    if not isinstance(mapping_lbic_id, str) or not isinstance(announce_type, str):
        raise _request_error()
    if bool(mapping_lbic_id) != bool(announce_type) or (mapping_lbic_id and not lawmaking._valid_metadata(mapping_lbic_id, announce_type)):
        raise _request_error()
    found = _read(lambda: lawmaking.notice(seq, mapping_lbic_id, announce_type))
    text = found["text"]
    fits = len(text) <= service.MAX_CHARS
    problem = public_rules.input_problem(text)
    return public_rules.envelope({**found, "policy_text": text, "full_length": len(text), "clipped": False,
        "cost_usd": 0, "estimate_arguments": {"policy_text": text} if fits else None,
        "input_warning": problem,
        "next_action": "estimate_arguments를 estimate에 넣어 무료로 비용을 확인하세요." if fits and not problem
                       else "문안의 입력 경고를 확인한 뒤 다룰 범위를 명시해 estimate에 넣으세요.",
        "source_notice": "공개 입법예고의 이유·주요내용 원문입니다. 조회는 무료이며 모델 실행은 시작하지 않았습니다."})
