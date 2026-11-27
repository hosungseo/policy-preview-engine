import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_press.py"
spec = importlib.util.spec_from_file_location("fetch_press", SCRIPT)
fetch_press = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_press)

HTML = """<html><script>var x=1;</script><div>보도자료</div>
<p>□ 수도권·규제지역 주담대 최대한도를 6억원으로&nbsp;제한</p>
<p>○ 생애최초 LTV 70%<br>○ 전입의무 6개월</p><p>□ 전세대출 보증비율 축소</p><p>붙임 1.</p></html>"""


def test_cut_copies_between_anchors_verbatim():
    text = fetch_press.html_to_text(HTML)
    out = fetch_press.cut(text, [("□ 수도권", "전입의무 6개월"), ("□ 전세대출", "축소")])
    assert out == ("□ 수도권·규제지역 주담대 최대한도를 6억원으로 제한\n○ 생애최초 LTV 70%\n○ 전입의무 6개월"
                   "\n…\n□ 전세대출 보증비율 축소")


def test_cut_single_line_and_missing_anchor():
    text = fetch_press.html_to_text(HTML)
    assert fetch_press.cut(text, [("□ 전세대출 보증비율 축소", "축소")]) == "□ 전세대출 보증비율 축소"
    with pytest.raises(ValueError):
        fetch_press.cut(text, [("없는 문장", "축소")])


def _hwpx(section_xml: str) -> bytes:
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", section_xml)
    return buf.getvalue()


def test_hwpx_paragraphs_become_lines_in_document_order():
    hp = 'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"'
    xml = (f'<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" {hp}>'
           '<hp:p><hp:run><hp:t>□ 서울 전역   규제지역</hp:t></hp:run><hp:run><hp:t> 지정</hp:t></hp:run></hp:p>'
           '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>표 칸</hp:t></hp:run></hp:p>'
           '</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
           '<hp:p><hp:run><hp:t>○ 주담대 한도 차등</hp:t></hp:run></hp:p></hs:sec>')
    assert fetch_press.to_text(_hwpx(xml)).splitlines() == ["□ 서울 전역 규제지역 지정", "표 칸", "○ 주담대 한도 차등"]
    assert fetch_press.to_text("<p>가</p><p>나</p>".encode("utf-8")).splitlines() == ["가", "나"]
