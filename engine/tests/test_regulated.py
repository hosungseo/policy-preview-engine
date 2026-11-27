import pytest

from pp import regulated

PERIODS = [
    {"from": "2023-01-05", "areas": ["서울-강남구"], "partial": [], "source": "a"},
    {"from": "2025-10-16", "areas": ["서울-*", "경기-과천시"], "partial": [], "source": "b"},
    {"from": "2026-07-01", "areas": ["서울-*", "경기-과천시", "경기-구리시"], "partial": ["경기-화성시"], "source": "c"},
]


def test_status_uses_the_period_in_force_on_the_date():
    s = regulated.status
    assert s("서울-강남구", "2025-06-27", PERIODS) == "규제지역"
    assert s("서울-노원구", "2025-10-15", PERIODS) == "비규제 수도권"  # announced the day before it took effect
    assert s("서울-노원구", "2025-10-16", PERIODS) == "규제지역"
    assert s("경기-구리시", "2026-06-30", PERIODS) == "비규제 수도권"
    assert s("경기-구리시", "2026-08-13", PERIODS) == "규제지역"
    assert s("경기-화성시", "2026-08-13", PERIODS) == "일부(구분 불가)"
    assert s("부산-해운대구", "2026-08-13", PERIODS) == "지방"
    assert s("인천-연수구", "2022-01-01", PERIODS) == "비규제 수도권"


def test_load_rejects_periods_without_source(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('{"periods": [{"from": "2025-06-27", "areas": [], "partial": []}]}', encoding="utf-8")
    with pytest.raises(ValueError):
        regulated.load(p)


def test_unknown_areas_lists_names_the_persona_db_does_not_have():
    assert regulated.unknown_areas(PERIODS, {"서울-강남구", "경기-과천시", "경기-화성시"}) == ["경기-구리시"]
