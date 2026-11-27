"""Notice tools use the real parsers with offline API/public-page responses."""
import asyncio
import json
from datetime import date

import pytest

from pp import lawmaking, mcp_notices, mcp_setup, service
from pp.jobs import Jobs
from pp.mcp import create_server
from test_lawmaking import API_XML, DETAIL_XML, LIST_HTML, NOTICE_HTML, REFUSED, serve


@pytest.fixture(autouse=True)
def notice_clock(monkeypatch):
    class Today(date):
        @classmethod
        def today(cls):
            return cls(2026, 11, 27)

    monkeypatch.setattr(mcp_notices, "date", Today)
    monkeypatch.delenv("LAWMAKING_OC", raising=False)


def test_keyless_recent_search_and_raw_detail(monkeypatch):
    seen = serve(monkeypatch, [("/gcom/ogLmPp/89312", NOTICE_HTML), ("/gcom/ogLmPp", LIST_HTML)])
    recent = mcp_notices.find_notice()
    assert recent["source"] == "web" and recent["items"][0]["seq"] == "89312"
    assert recent["cost_usd"] == 0 and recent["as_of"] == "2026-11-27"
    assert mcp_notices.find_notice("지방행정")["items"]
    assert seen[-1][1] == {"lsNm": "지방행정"}
    got = mcp_notices.get_notice("89312")
    assert got["source"] == "web" and got["clipped"] is False
    assert got["policy_text"] == got["text"]
    assert "개정이유" in got["text"] and "주요내용" in got["text"]
    assert "의견제출" not in got["text"]
    assert service.estimate(**got["estimate_arguments"])["policy_chars"] == got["full_length"]


def test_api_metadata_is_carried_to_detail_and_fallback(monkeypatch):
    monkeypatch.setenv("LAWMAKING_OC", "test-account-never-reflected")
    seen = serve(monkeypatch, [("/rest/ogLmPp.xml", API_XML), ("/rest/ogLmPp/89350/0/TYPE5.xml", DETAIL_XML)])
    row = mcp_notices.find_notice("행정")["items"][0]
    got = mcp_notices.get_notice(row["seq"], row["mapping_lbic_id"], row["announce_type"])
    assert got["source"] == "api"
    assert "test-account-never-reflected" not in json.dumps(got)
    assert seen[-1][1] == {"OC": "test-account-never-reflected"}
    serve(monkeypatch, [("/rest/ogLmPp.xml", REFUSED), ("/gcom/ogLmPp", LIST_HTML)])
    assert mcp_notices.find_notice("행정")["source"] == "web"


def test_expired_future_and_unknown_periods_are_not_open(monkeypatch):
    past = LIST_HTML.replace("2026. 12. 15.", "2026. 11. 26.")
    future = LIST_HTML.replace("2026. 11. 5.", "2026. 12. 5.")
    unknown = LIST_HTML.replace("2026. 12. 15.", "미정")
    for body in (past, future, unknown):
        serve(monkeypatch, [("/gcom/ogLmPp", body)])
        result = mcp_notices.find_notice()
        assert not result["items"] and result["total"] is None
    assert result["warnings"]


@pytest.mark.parametrize("query,page", [("한", 1), ("a" * 51, 1), ("", 0), ("", True), ("", 51)])
def test_invalid_search_never_fetches(query, page, monkeypatch):
    monkeypatch.setattr(lawmaking, "_get", lambda *a, **k: pytest.fail("invalid request fetched"))
    with pytest.raises(mcp_setup.SetupError) as exc:
        mcp_notices.find_notice(query, page)
    assert exc.value.code == "invalid_notice_request"


@pytest.mark.parametrize("args", [("../secret",), ("89350", "0"), ("89350", "0", "secret")])
def test_invalid_notice_metadata_never_fetches(args, monkeypatch):
    monkeypatch.setattr(lawmaking, "_get", lambda *a, **k: pytest.fail("invalid request fetched"))
    with pytest.raises(mcp_setup.SetupError):
        mcp_notices.get_notice(*args)


def test_long_body_is_preserved_and_requires_explicit_selection(monkeypatch):
    text = "1. 개정이유\n" + "아" * 31000
    monkeypatch.setattr(lawmaking, "notice", lambda *a: {"text": text})
    result = mcp_notices.get_notice("89350")
    assert result["text"] == text and not result["clipped"]
    assert result["estimate_arguments"] is None


def test_mcp_notice_tools_and_safe_failure_guidance(monkeypatch):
    serve(monkeypatch, [("/gcom/ogLmPp/89312", NOTICE_HTML), ("/gcom/ogLmPp", LIST_HTML)])
    jobs = Jobs()
    server = create_server(jobs)

    async def scenario():
        for name, arguments in [("find_notice", {}), ("get_notice", {"seq": "89312"})]:
            result = await server.call_tool(name, arguments)
            assert not result.isError
            assert result.structuredContent["cost_usd"] == 0
        def fail(*args, **kwargs):
            raise lawmaking.LawmakingError("account_refused", "provider reflected secret-account-key")
        monkeypatch.setattr(lawmaking, "_get", fail)
        for name, arguments in [("find_notice", {}), ("get_notice", {"seq": "89312"})]:
            result = await server.call_tool(name, arguments)
            assert result.isError
            assert result.structuredContent["code"] == "lawmaking_unavailable"
            assert "secret-account-key" not in result.model_dump_json()
            assert result.structuredContent["next_action"]
            assert result.structuredContent["free_alternative"]

    try:
        asyncio.run(scenario())
    finally:
        jobs.close()
