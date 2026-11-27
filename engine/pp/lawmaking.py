"""Legislative notices from 국민참여입법센터 for policy-preview input.

The authenticated open API supplies both the search metadata and notice body.  The public
notice page remains a read-only fallback when no approved API account is available.
"""
from __future__ import annotations

import html
import os
import re

from defusedxml import ElementTree as ET

from . import net

BASE = "https://opinion.lawmaking.go.kr"
API_BASE = "https://www.lawmaking.go.kr"
TIMEOUT = 20
MAX_ITEMS = 30


class LawmakingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def base_url() -> str:
    return (os.environ.get("LAWMAKING_BASE_URL") or BASE).rstrip("/")


def api_base_url() -> str:
    return (os.environ.get("LAWMAKING_API_BASE_URL") or API_BASE).rstrip("/")


def account() -> str:
    return (os.environ.get("LAWMAKING_OC") or "").strip()


def notice_url(seq: str) -> str:
    return f"{BASE}/gcom/ogLmPp/{seq}"


def _get(url: str, params: dict | None = None) -> str:
    try:
        return net.get(url, params=params, timeout=TIMEOUT).decode("utf-8", errors="replace")
    except (net.NetError, net.HTTPError, TimeoutError, OSError) as e:
        raise LawmakingError("unreachable", "국민참여입법센터에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.") from e


def html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    s = re.sub(r"(?s)<!--.*?-->", "", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</?(p|div|li|tr|td|th|h\d|dd|dt|ul|ol|table)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines()]
    return "\n".join(line for line in lines if line)


def _period(start: str, end: str) -> str:
    start, end = start.strip(), end.strip().lstrip("~").strip()
    return f"{start} ~ {end}" if start and end else start or end


def _api_root(xml: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise LawmakingError("bad_response", "입법예고 API 응답을 읽지 못했습니다.") from e
    ret = (root.findtext("./retMsg") or root.findtext(".//retMsg") or "").strip()
    if ret != "200":
        code = "account_refused" if ret == "401" else "bad_response"
        raise LawmakingError(code, f"입법예고 API가 요청을 거절했습니다({ret or '응답 없음'}).")
    return root


def _api_item(node: ET.Element) -> dict:
    def get(tag: str) -> str:
        return html.unescape((node.findtext(tag) or "").strip())

    seq = get("ogLmPpSeq")
    return {"seq": seq, "title": get("lsNm"), "agency": get("asndOfiNm"), "kind": get("lsClsNm"),
            "period": _period(get("stYd"), get("edYd")), "url": notice_url(seq),
            "mapping_lbic_id": get("mappingLbicId"), "announce_type": get("announceType")}


def parse_api_result(xml: str) -> dict:
    """Parse the list API's real success envelope and its pagination total."""
    root = _api_root(xml)
    try:
        total = int((root.findtext("./totalCnt") or "0").strip())
    except ValueError as e:
        raise LawmakingError("bad_response", "입법예고 API의 검색 건수를 읽지 못했습니다.") from e
    items = [_api_item(node) for node in root.findall("./list/ApiList04Vo") if (node.findtext("ogLmPpSeq") or "").strip()]
    return {"items": items, "total": total}


def parse_api(xml: str) -> list[dict]:
    """Backward-compatible rows of the list API."""
    return parse_api_result(xml)["items"]


def parse_web_list(raw: str) -> list[dict]:
    """Rows of the public list page (same notices, no account needed)."""
    items = []
    for row in re.split(r"(?i)<tr\b", raw):
        link = re.search(r'href="/gcom/ogLmPp/(\d+)\?[^\"]*"\s+title="([^\"]*)"', row)
        if not link:
            continue

        def cell(label: str) -> list[str]:
            m = re.search(rf'(?s)data-th="{label}[^\"]*"[^>]*>(.*?)</td>', row)
            return html_to_text(m.group(1)).splitlines() if m else []

        org, dates = cell("소관부처"), cell("입법의견 접수기간")
        items.append({"seq": link.group(1), "title": html.unescape(link.group(2)).strip(),
                      "agency": org[0] if org else "", "kind": org[1].strip("()") if len(org) > 1 else "",
                      "period": _period(dates[0] if dates else "", dates[1] if len(dates) > 1 else ""),
                      "url": notice_url(link.group(1))})
    return items


def search(query: str, page: int = 1) -> dict:
    """Search title. API results retain required detail metadata; result count is never capped."""
    query = query.strip()
    if not query:
        return {"items": [], "source": "web", "total": 0, "capped": False}
    oc = account()
    if oc:
        url = f"{api_base_url()}/rest/ogLmPp.xml"
        try:
            result = parse_api_result(_get(url, {"OC": oc, "lsNm": query, "pageIndex": page, "pageSize": MAX_ITEMS}))
            items = result["items"][:MAX_ITEMS]
            return {"items": items, "source": "api", "total": result["total"], "page": page,
                    "more": page * MAX_ITEMS < result["total"], "capped": result["total"] > len(items)}
        except LawmakingError:
            # The public list is safe to use when the API account or upstream API is unavailable.
            pass
    url = f"{base_url()}/gcom/ogLmPp"
    items = parse_web_list(_get(url, {"lsNm": query}))[:MAX_ITEMS]
    # The public page's list markup does not reliably expose a total. Do not report a page length as a total.
    return {"items": items, "source": "web", "total": None, "page": 1, "more": False, "capped": False}


def recent(limit: int = MAX_ITEMS, page: int = 1) -> dict:
    """Notices currently open for comment, newest first, with no title filter (diff=0 = 진행)."""
    oc = account()
    if oc:
        try:
            result = parse_api_result(_get(f"{api_base_url()}/rest/ogLmPp.xml",
                                           {"OC": oc, "diff": "0", "pageIndex": page, "pageSize": limit}))
            items = result["items"][:limit]
            return {"items": items, "source": "api", "total": result["total"], "page": page,
                    "more": page * limit < result["total"], "capped": result["total"] > len(items)}
        except LawmakingError:
            pass
    items = parse_web_list(_get(f"{base_url()}/gcom/ogLmPp"))[:limit]
    return {"items": items, "source": "web", "total": None, "page": 1, "more": False, "capped": False}


def _valid_metadata(mapping_lbic_id: str, announce_type: str) -> bool:
    return bool(re.fullmatch(r"\d{1,20}", mapping_lbic_id) and re.fullmatch(r"TYPE\d{1,4}", announce_type))


def reason_and_main_contents(text: str) -> str:
    """The numbered 이유·주요내용 section, excluding 의견제출 and the notice boilerplate."""
    start = re.search(r"(?m)^\s*1\.\s*(?:(?:제정|개정|폐지)\s*이유(?:\s*및\s*주요내용)?|제정이유\s*및\s*주요내용)", text)
    if not start:
        raise LawmakingError("not_found", "입법예고문에서 이유와 주요내용을 찾지 못했습니다.")
    end = re.search(r"(?m)^\s*\d+\.\s*의견\s*제출", text[start.end():])
    if not end:
        raise LawmakingError("not_found", "입법예고문에서 의견제출 항목을 찾지 못했습니다.")
    return text[start.start():start.end() + end.start()].strip()


def parse_api_notice(xml: str, seq: str, mapping_lbic_id: str, announce_type: str) -> dict:
    """Parse the authenticated detail response. lmPpCts is HTML supplied by the API."""
    root = _api_root(xml)
    info = root.find("./info/ApiDetile04Vo")
    if info is None:
        raise LawmakingError("bad_response", "입법예고 API의 상세 정보를 읽지 못했습니다.")

    def get(tag: str) -> str:
        return html.unescape((info.findtext(tag) or "").strip())

    raw_body = html_to_text(get("lmPpCts"))
    if not raw_body:
        raise LawmakingError("bad_response", "입법예고 API에 본문이 없습니다.")
    body = reason_and_main_contents(raw_body)
    returned_seq = get("ogLmPpSeq")
    if returned_seq and returned_seq != seq:
        raise LawmakingError("bad_response", "입법예고 API의 상세 번호가 검색 결과와 다릅니다.")
    return {"seq": seq, "title": get("lsNm"), "agency": get("asndOfiNm"), "kind": get("lsClsNm"),
            "period": _period(get("stYd"), get("edYd")), "url": notice_url(seq), "text": body, "source": "api"}


def _after(lines: list[str], label: str) -> str:
    return lines[lines.index(label) + 1] if label in lines[:-1] else ""


def clip(text: str, limit: int) -> str:
    """Longest run of whole lines within `limit` characters."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit + 1)
    return text[:cut if cut > 0 else limit].rstrip()


def parse_notice(raw: str, seq: str) -> dict:
    text = html_to_text(raw)
    lines = text.splitlines()
    views = next((i for i, line in enumerate(lines) if re.fullmatch(r"조회수[\d,]+회", line)), None)
    title = next((line for line in reversed(lines[:views]) if len(line) > 6), "") if views else ""
    if not title:
        raise LawmakingError("not_found", "입법예고문에서 제목을 찾지 못했습니다.")
    return {"seq": seq, "title": title, "agency": _after(lines, "소관부처"), "kind": _after(lines, "법령종류"),
            "period": _after(lines, "접수기간"), "url": notice_url(seq),
            "text": reason_and_main_contents(text), "source": "web"}


def notice(seq: str, mapping_lbic_id: str = "", announce_type: str = "") -> dict:
    """Read a notice using search-supplied API metadata, or the public page for compatibility."""
    if not re.fullmatch(r"\d{1,10}", seq):
        raise LawmakingError("not_found", "입법예고 번호가 올바르지 않습니다.")
    if bool(mapping_lbic_id) != bool(announce_type) or (mapping_lbic_id and not _valid_metadata(mapping_lbic_id, announce_type)):
        raise LawmakingError("invalid_metadata", "검색 결과의 입법예고 정보가 올바르지 않습니다. 다시 검색해 주세요.")
    oc = account()
    if oc and mapping_lbic_id:
        url = f"{api_base_url()}/rest/ogLmPp/{seq}/{mapping_lbic_id}/{announce_type}.xml"
        try:
            return parse_api_notice(_get(url, {"OC": oc}), seq, mapping_lbic_id, announce_type)
        except LawmakingError:
            # Do not invent metadata or an API body. The public notice remains an explicit web fallback.
            pass
    return parse_notice(_get(f"{base_url()}/gcom/ogLmPp/{seq}"), seq)
