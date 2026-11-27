import pytest

from pp import jev, series_questions as sq

TEXT = "주요 내용\n□ 주담대 한도 6억 원 제한\n○ 생애최초 LTV 70%\n□ 전세대출 보증비율 축소\n○ 1주택자 전세대출 DSR 반영"


def test_measure_segments_follow_top_level_bullets():
    segs = sq.measure_segments(TEXT)
    assert [s["id"] for s in segs] == ["s1", "s2"]
    assert segs[0]["label"] == "주담대 한도 6억 원 제한"
    assert segs[1]["text"].startswith("□ 전세대출") and "DSR" in segs[1]["text"]


def test_measure_segments_rejects_too_many_bullets():
    with pytest.raises(ValueError):
        sq.measure_segments("\n".join(f"□ 항목 {i}번에 관한 내용입니다" for i in range(9)))


def test_measure_segments_fall_back_to_numbered_headings():
    segs = sq.measure_segments("1. 추진 배경\n고령화가 빨라지고 있다는 설명입니다.\n2. 주요 내용\n가. 기준 연령을 올린다는 내용입니다.")
    assert len(segs) >= 2


LISTED = ("▴ 한도 제한(6억원), 전입의무 부과 등 추가 조치\n…\n우선, 수도권 추가 주택구입 주담대를 금지한다.\n* 규제지역 : 강남구\n…\n"
          "➋ 생애 최초 LTV를 강화한다.\n…\n우선, 수도권 전세대출 보증비율을 강화한다.")


def test_measure_segments_follow_listed_provisions_in_order():
    segs = sq.measure_segments(LISTED, ["우선, 수도권", {"start": "➋ 생애", "label": "전입의무 부과"}, "우선, 수도권"])
    assert [s["label"] for s in segs] == ["우선, 수도권 추가 주택구입 주담대를 금지한다.", "전입의무 부과",
                                          "우선, 수도권 전세대출 보증비율을 강화한다."]
    assert segs[0]["text"] == "우선, 수도권 추가 주택구입 주담대를 금지한다.\n* 규제지역 : 강남구"  # the "…" line is dropped
    assert segs[1]["text"] == "➋ 생애 최초 LTV를 강화한다."
    assert LISTED[segs[2]["start"]:segs[2]["end"]] == segs[2]["text"]


def test_listed_provisions_must_start_lines_and_labels_must_be_verbatim():
    with pytest.raises(ValueError):
        sq.measure_segments(TEXT, ["한도 6억", "□ 전세대출"])  # not at the start of a line
    with pytest.raises(ValueError):
        sq.measure_segments(TEXT, [{"start": "□ 주담대", "label": "없는 말"}, "□ 전세대출"])
    with pytest.raises(ValueError):
        sq.measure_segments(TEXT, ["□ 주담대"])  # a single provision


def test_default_label_drops_markers_and_clips_to_40():
    segs = sq.measure_segments("머리말\n➊ 첫 조항입니다\n(2) " + "가" * 50, ["➊", "(2)"])
    assert [s["label"] for s in segs] == ["첫 조항입니다", "가" * 39 + "…"]


def test_questions_and_summaries_with_mock(monkeypatch):
    monkeypatch.setenv("PP_JEV_PROVIDER", "mock")
    segs = sq.measure_segments(TEXT)
    qs = sq.measure_questions(segs)
    assert set(qs) == {"stance", "direct", "seg_s1", "seg_s2", "pos_s1", "pos_s2", *sq.HOUSING}
    row = sq.summarize_measure(jev.evaluate({"x": 1}, qs), segs)
    assert abs(row["favor"] + row["reserve"] - 1) < 1e-3
    assert set(row["housing"]) == set(sq.HOUSING) and set(row["positions"]) == {"s1", "s2"}
    tenure = sq.summarize_tenure(jev.evaluate({"x": 1}, sq.tenure_question()))
    assert set(tenure["tenure"]) == set(sq.TENURE) and abs(sum(tenure["tenure"].values()) - 1) < 1e-3
