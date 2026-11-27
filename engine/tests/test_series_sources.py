"""The housing series files carry a licence for every piece of outside text (see data/SOURCES.md).

정책브리핑(korea.kr) text is kept only under 공공누리 제1유형; anything without a usable marking is replaced by our own
summary and keeps just its title and link. The same holds for the published web bundle.
"""
import json
from pathlib import Path

from pp import series, series_questions

ROOT = Path(__file__).resolve().parents[2]
ENGINE_SERIES = ROOT / "engine" / "series" / "housing.json"
WEB_SERIES = ROOT / "web" / "public" / "series" / "housing.json"
REGULATED = ROOT / "engine" / "series" / "regulated_areas.json"
KOGL1 = "공공누리 제1유형"


def _check_measure_source(m: dict) -> None:
    src = m["source"]
    assert src.get("url") and src.get("title") and src.get("provider") and src.get("license"), m["id"]
    if "korea.kr" in src["url"]:
        assert src["license"].startswith(KOGL1) and src.get("text_kind") != "summary", m["id"]
    else:
        # no usable marking: our summary only, no copied excerpt anchors
        assert src.get("text_kind") == "summary" and "excerpts" not in src, m["id"]


def test_engine_series_loads_and_every_measure_is_licensed():
    s = series.load_series(ENGINE_SERIES)
    for m in s["measures"]:
        _check_measure_source(m)
        if m["source"].get("text_kind") == "summary":
            assert series_questions.measure_segments(m["text"], m.get("provisions"))


def test_web_bundle_matches_the_engine_text_and_licences():
    engine = {m["id"]: m for m in json.loads(ENGINE_SERIES.read_text(encoding="utf-8"))["measures"]}
    for m in json.loads(WEB_SERIES.read_text(encoding="utf-8"))["measures"]:
        _check_measure_source(m)
        assert m["text"] == engine[m["id"]]["text"]
        segs = series_questions.measure_segments(engine[m["id"]]["text"], engine[m["id"]].get("provisions"))
        assert [s["label"] for s in m["segments"]] == [s["label"] for s in segs]


def test_regulated_evidence_is_licensed_or_summarised():
    for p in json.loads(REGULATED.read_text(encoding="utf-8"))["periods"]:
        for e in p.get("evidence", []):
            if "korea.kr" in e["url"]:
                assert e["license"].startswith(KOGL1) and e.get("title")
            else:
                assert e.get("kind") == "summary" and e.get("license")
