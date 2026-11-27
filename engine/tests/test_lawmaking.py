"""Legislative notice adapter: real API envelopes, web fallback, and service routes."""
import pytest
from fastapi.testclient import TestClient

from pp import lawmaking
from ppservice import auth
from ppservice.app import create_app

from test_svc_survey import FakeJev, H, make_settings

API_XML = """<result><retMsg>200</retMsg><totalCnt>33</totalCnt><pageIndex>1</pageIndex><pageSize>30</pageSize><list>
<ApiList04Vo><ogLmPpSeq>89350</ogLmPpSeq><lsNm>행정정보 공동이용 법령안 입법예고</lsNm>
<lsClsNm>대통령령</lsClsNm><asndOfiNm>법제처</asndOfiNm><stYd>2026. 11. 6.</stYd><edYd>2026. 12. 16.</edYd>
<mappingLbicId>0</mappingLbicId><announceType>TYPE5</announceType></ApiList04Vo></list></result>"""
DETAIL_XML = """<result><retMsg>200</retMsg><info><ApiDetile04Vo><ogLmPpSeq>89350</ogLmPpSeq><lsNm>행정정보 공동이용 법령안 입법예고</lsNm>
<asndOfiNm>법제처 공고 제2026-170호</asndOfiNm><lmTpNm>일부개정</lmTpNm><lsClsNm>대통령령</lsClsNm>
<stYd>2026. 11. 6.</stYd><edYd>2026. 12. 16.</edYd><lmPpCts><![CDATA[<p>공고 머리말</p><p>1. 제정이유 및 주요내용</p><p>행정서류를 간소화합니다.</p><p>2. 주요내용</p><p>공동이용을 확대합니다.</p><p>3. 의견제출</p><p>전화번호와 제출방법</p>]]></lmPpCts></ApiDetile04Vo></info></result>"""
REFUSED = "<result><retMsg>401</retMsg></result>"
LIST_HTML = """<table><tr><td data-th="번호">1</td><td data-th="법령 제명" class="subject">
<a href="/gcom/ogLmPp/89312?lsNm=x" title="지방행정제재ㆍ부과금법 시행규칙 일부개정령안 입법예고">…</a></td>
<td data-th="소관부처 (법령종류)"><p>행정안전부</p><p>(부령)</p></td>
<td data-th="입법의견 접수기간"><p>2026. 11. 5.</p><p>~2026. 12. 15.</p></td></tr></table>"""
NOTICE_HTML = """<html><script>x=1</script><p>화면크기 확대</p>
<h3>행정기본법 시행령 일부개정령안 입법예고</h3><span>일부</span><p>조회수1,423회</p>
<dl><dt>법령종류</dt><dd>대통령령</dd><dt>접수기간</dt><dd>2026. 11. 6. ~ 2026. 11. 26.</dd><dt>소관부처</dt><dd>법제처</dd></dl>
<p>1. 개정이유</p><p>입법영향분석 제도를&nbsp;활성화하려는 것임.</p>
<p>2. 주요내용</p><p>수요조사 대상을 지방자치단체까지 확대함.</p>
<p>3. </p><p>의견제출</p><p>의견이 있는 기관은 제출하여 주시기 바랍니다.</p></html>"""


def serve(monkeypatch, pages):
    seen = []

    def get(url, params=None):
        seen.append((url, params))
        return next(body for part, body in pages if part in url)

    monkeypatch.setattr(lawmaking, "_get", get)
    return seen


def test_search_accepts_real_success_envelope_and_keeps_detail_metadata(monkeypatch):
    monkeypatch.setenv("LAWMAKING_OC", "tester")
    seen = serve(monkeypatch, [("/rest/ogLmPp.xml", API_XML)])
    found = lawmaking.search("행정")
    assert "/rest/ogLmPp.xml" in seen[0][0]
    assert seen[0][1] == {"OC": "tester", "lsNm": "행정", "pageIndex": 1, "pageSize": 30}
    assert found["source"] == "api" and found["total"] == 33 and found["capped"]
    assert found["items"] == [{"seq": "89350", "title": "행정정보 공동이용 법령안 입법예고", "agency": "법제처",
                                "kind": "대통령령", "period": "2026. 11. 6. ~ 2026. 12. 16.",
                                "url": "https://opinion.lawmaking.go.kr/gcom/ogLmPp/89350",
                                "mapping_lbic_id": "0", "announce_type": "TYPE5"}]


def test_api_parser_decodes_entities_and_keeps_real_envelope_fields():
    xml = """<result><retMsg>200</retMsg><totalCnt>2</totalCnt><list>
    <ApiList04Vo><ogLmPpSeq>1</ogLmPpSeq><lsNm>가 &amp; 나</lsNm><asndOfiNm>부처</asndOfiNm><lsClsNm>법률</lsClsNm><mappingLbicId>10</mappingLbicId><announceType>TYPE2</announceType></ApiList04Vo>
    <ApiList04Vo><ogLmPpSeq>2</ogLmPpSeq><lsNm><![CDATA[&lt;제목&gt;]]></lsNm><asndOfiNm>청</asndOfiNm><lsClsNm>부령</lsClsNm><mappingLbicId>20</mappingLbicId><announceType>TYPE3</announceType></ApiList04Vo>
    </list></result>"""
    parsed = lawmaking.parse_api_result(xml)
    assert parsed["total"] == 2
    assert [(row["seq"], row["title"], row["mapping_lbic_id"], row["announce_type"]) for row in parsed["items"]] == [
        ("1", "가 & 나", "10", "TYPE2"), ("2", "<제목>", "20", "TYPE3")]


def test_api_detail_uses_search_supplied_metadata(monkeypatch):
    monkeypatch.setenv("LAWMAKING_OC", "tester")
    seen = serve(monkeypatch, [("/rest/ogLmPp/89350/0/TYPE5.xml", DETAIL_XML)])
    found = lawmaking.notice("89350", "0", "TYPE5")
    assert "/rest/ogLmPp/89350/0/TYPE5.xml" in seen[0][0]
    assert seen[0][1] == {"OC": "tester"}
    assert found["source"] == "api"
    assert found["text"] == "1. 제정이유 및 주요내용\n행정서류를 간소화합니다.\n2. 주요내용\n공동이용을 확대합니다."
    assert "공고 머리말" not in found["text"] and "의견제출" not in found["text"]


def test_reason_section_requires_both_headings():
    with pytest.raises(lawmaking.LawmakingError, match="이유와 주요내용"):
        lawmaking.reason_and_main_contents("공고만 있습니다.\n2. 의견제출")
    with pytest.raises(lawmaking.LawmakingError, match="의견제출"):
        lawmaking.reason_and_main_contents("1. 제정이유 및 주요내용\n내용만 있습니다.")


@pytest.mark.parametrize("oc", ["", "refused"])
def test_search_reads_public_page_when_api_is_not_available(monkeypatch, oc):
    monkeypatch.setenv("LAWMAKING_OC", oc)
    seen = serve(monkeypatch, [("/rest/ogLmPp.xml", REFUSED), ("/gcom/ogLmPp", LIST_HTML)])
    found = lawmaking.search("지방행정")
    assert found["source"] == "web" and found["total"] is None and len(seen) == (2 if oc else 1)
    assert found["items"][0]["seq"] == "89312"
    assert seen[-1][1] == {"lsNm": "지방행정"}


def test_notice_web_fallback_and_metadata_validation(monkeypatch):
    monkeypatch.delenv("LAWMAKING_OC", raising=False)
    serve(monkeypatch, [("/gcom/ogLmPp/89346", NOTICE_HTML)])
    found = lawmaking.notice("89346")
    assert found["source"] == "web"
    assert lawmaking.clip(found["text"], 34) == "1. 개정이유\n입법영향분석 제도를 활성화하려는 것임."
    with pytest.raises(lawmaking.LawmakingError, match="정보가 올바르지"):
        lawmaking.notice("89346", "0", "TYPEoops")
    with pytest.raises(lawmaking.LawmakingError):
        lawmaking.notice("../etc")


def test_routes_passes_metadata_and_keeps_old_detail_route(tmp_path, monkeypatch):
    monkeypatch.setenv("LAWMAKING_OC", "tester")
    serve(monkeypatch, [("/rest/ogLmPp.xml", API_XML), ("/rest/ogLmPp/89350/0/TYPE5.xml", DETAIL_XML),
                        ("/gcom/ogLmPp/89346", NOTICE_HTML)])
    app = create_app(make_settings(tmp_path, monkeypatch, PP_MAX_POLICY=34), start_workers=False, evaluate=FakeJev())
    code = auth.add_user(app.state.db, "a@x.go.kr")
    with TestClient(app) as client:
        assert client.get("/api/lawmaking?q=행정").status_code == 401
        client.post("/api/login", json={"email": "a@x.go.kr", "code": code}, headers=H)
        assert client.get("/api/lawmaking?q=행").status_code == 422
        search = client.get("/api/lawmaking?q=행정").json()
        assert search["total"] == 33 and search["items"][0]["mapping_lbic_id"] == "0"
        got = client.get("/api/lawmaking/89350?mapping_lbic_id=0&announce_type=TYPE5").json()
        assert got["source"] == "api" and got["clipped"] and got["full_length"] > len(got["text"])
        assert client.get("/api/lawmaking/89350?mapping_lbic_id=0").status_code == 422


def test_recent_lists_open_notices_without_a_title_filter(monkeypatch):
    monkeypatch.setenv("LAWMAKING_OC", "tester")
    seen = serve(monkeypatch, [("/rest/ogLmPp.xml", API_XML)])
    found = lawmaking.recent()
    assert found["source"] == "api" and found["items"][0]["seq"] == "89350"
    url, params = seen[0]
    assert params["diff"] == "0" and "lsNm" not in params and params["pageIndex"] == 1
    assert found["more"] is True  # 33 open notices, 30 per page
    lawmaking.recent(page=2)
    assert seen[1][1]["pageIndex"] == 2
