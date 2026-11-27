import numpy as np

from pp import semantic

ROWS = [
    {"id": 1, "name": "노인자", "age": 63, "sex": "여자", "district": "세종-세종", "occupation": "무직",
     "family_type": "혼자 거주", "persona": "노인자 씨는 세종시에서 조용히 지냅니다.",
     "professional_persona": "노인자 씨는 은퇴했습니다.", "family_persona": "", "cultural_background": ""},
    {"id": 2, "name": "김영숙", "age": 67, "sex": "여자", "district": "서울-중랑구", "occupation": "청소원",
     "family_type": "배우자와 거주", "persona": "김영숙 씨는 매일 지하철로 출근합니다.",
     "professional_persona": "김영숙씨는 새벽 첫차를 탑니다.", "family_persona": "", "cultural_background": ""},
]


def fake_encoder(seen):
    def encode(texts):
        seen.extend(texts)
        # dimension 0 = mentions the subway, dimension 1 = anything else
        return np.array([[1.0, 0.1] if "지하철" in t else [0.1, 1.0] for t in texts], dtype=np.float32)
    return encode


def test_strip_name_variants():
    assert semantic.strip_name("노인자 씨는 세종에 삽니다. 노인자씨의 집", "노인자") == "이 사람는 세종에 삽니다. 이 사람의 집"
    assert semantic.strip_name("이름 없는 서술", "") == "이름 없는 서술"


def test_text_without_name_drops_every_occurrence():
    text = semantic.persona_text_without_name(ROWS[1])
    assert "김영숙" not in text and "지하철로 출근" in text and "청소원" in text


def test_rerank_uses_name_free_text():
    seen = []
    ranked = semantic.rerank_without_names(ROWS, np.array([1.0, 0.0], dtype=np.float32), k=2, encode=fake_encoder(seen))
    assert [pid for pid, _ in ranked] == [2, 1]
    assert all("노인자" not in t and "김영숙" not in t for t in seen)
    assert semantic.rerank_without_names([], np.array([1.0, 0.0]), k=3, encode=fake_encoder([])) == []


def test_similar_by_text():
    rows = ROWS + [{**ROWS[1], "id": 3, "name": "박철수", "persona": "박철수 씨도 지하철로 다닙니다."}]
    sims = semantic.similar_by_text(rows, k=1, key="id", encode=fake_encoder([]))
    assert sims[2] == [3] and sims[3] == [2]
