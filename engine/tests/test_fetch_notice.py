import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_notice.py"
spec = importlib.util.spec_from_file_location("fetch_notice", SCRIPT)
fetch_notice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_notice)

HTML = """<html><script>x=1</script><div>행정안전부 공고</div>
<p>1. 제정이유</p><p>안전사고로부터 국민의 생명ㆍ신체를&nbsp;보호하려는 것임.</p>
<p>2. 주요내용</p><p>가. 기업등의 범위(안 제5조)<br>소상공인은 제외하도록 함.</p>
<p>3. </p><p>의견제출</p><p>이 개정안에 대해 의견이 있는 기관은…</p></html>"""


def test_html_to_lines_and_extract():
    text = fetch_notice.html_to_text(HTML)
    body = fetch_notice.extract(text)
    assert body.splitlines() == [
        "1. 제정이유",
        "안전사고로부터 국민의 생명ㆍ신체를 보호하려는 것임.",
        "2. 주요내용",
        "가. 기업등의 범위(안 제5조)",
        "소상공인은 제외하도록 함.",
    ]
