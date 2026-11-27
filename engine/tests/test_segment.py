from pp import segment

SAMPLE = """1. 제정이유
안전사고로부터 국민의 생명ㆍ신체를 보호하기 위하여 시행령을 제정하려는 것임.
2. 주요내용
가. 안전사고 및 피해자의 범위(안 제2조부터 제3조까지)
1) 안전사고의 범위에 사망 또는 실종을 초래하는 재난을 포함하도록 함.
나. 기업등의 범위(안 제5조)
법 제7조에 따른 책무를 부담하는 기업등의 범위에 소상공인은 제외하도록 함.
"""


def test_split_drops_heading_only_segments():
    segs = segment.split_segments(SAMPLE)
    assert [s["label"] for s in segs] == [
        "1. 제정이유",
        "가. 안전사고 및 피해자의 범위(안 제2조부터 제3조까지)",
        "나. 기업등의 범위(안 제5조)",
    ]
    assert [s["id"] for s in segs] == ["s1", "s2", "s3"]
    for s in segs:
        assert SAMPLE[s["start"]:s["end"]] == s["text"]


def test_one_line_items_are_kept():
    text = "2. 주요 내용\n가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.\n나. 기초연금 수급자는 무임승차를 유지한다.\n"
    labels = [s["label"] for s in segment.split_segments(text)]
    assert labels == ["가. 무임승차 기준 연령을 단계적으로 70세까지 올린다.", "나. 기초연금 수급자는 무임승차를 유지한다."]


def test_preamble_and_no_heading():
    text = "【가상 정책안】 도시철도 무임승차 기준 연령 조정안입니다.\n1. 추진 배경\n고령화로 무임수송 손실이 커지고 있어 제도를 손보려는 것이다.\n"
    segs = segment.split_segments(text)
    assert segs[0]["label"] == "전문"
    assert segs[1]["label"] == "1. 추진 배경"
    plain = segment.split_segments("머리말 없이 한 문단으로 된 정책 설명입니다.")
    assert len(plain) == 1 and plain[0]["label"] == "전문"


def test_locate_ignores_whitespace_and_middle_dot_variants():
    loc = segment.locate("생명·신체를   보호", SAMPLE)
    assert loc is not None
    start, end = loc
    assert SAMPLE[start:end] == "생명ㆍ신체를 보호"


def test_locate_rejects_short_or_missing():
    assert segment.locate("범위", SAMPLE) is None
    assert segment.locate("전혀 없는 문구입니다", SAMPLE) is None
    assert segment.locate("", SAMPLE) is None


def test_segment_of():
    segs = segment.split_segments(SAMPLE)
    start, _ = segment.locate("소상공인은 제외", SAMPLE)
    assert segment.segment_of(start, segs) == "s3"
    assert segment.segment_of(len(SAMPLE) + 5, segs) is None
