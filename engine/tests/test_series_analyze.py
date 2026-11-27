from pp import series_analyze as sa

PEOPLE = {
    "a": {"province": "서울", "age": 25, "sex": "남자", "housing_type": "아파트",
          "tenure": {"own": 0.2, "jeonse": 0.6, "monthly": 0.2, "other": 0.0}},
    "b": {"province": "서울", "age": 45, "sex": "여자", "housing_type": "아파트",
          "tenure": {"own": 0.8, "jeonse": 0.1, "monthly": 0.1, "other": 0.0}},
    "c": {"province": "부산", "age": 65, "sex": "여자", "housing_type": "단독주택",
          "tenure": {"own": 1.0, "jeonse": 0.0, "monthly": 0.0, "other": 0.0}},
}
REG = {"a": "규제지역", "b": "규제지역", "c": "지방"}
SEGS = [{"id": "s1", "label": "한도"}]


def row(u, favor, stance=0.0, pos=0.0, opp=0.2, h=0.5):
    return {"uuid": u, "stance": stance, "stance_probs": [0.1, 0.1, round(0.8 - favor, 4), favor / 2, favor / 2],
            "favor": favor, "reserve": round(1 - favor, 4), "direct": 0.1, "segments": {"s1": 0.3},
            "positions": {"s1": pos}, "pos_oppose": {"s1": opp}, "housing": {k: h for k in sa.HOUSING}}


def test_condition_stats_groups_and_weights(monkeypatch):
    monkeypatch.setattr(sa, "SMALL_N", 2)
    st = sa.condition_stats([row("a", 0.2, -0.5), row("b", 0.6, 0.5), row("c", 0.8, 1.0)], PEOPLE, SEGS, REG)
    assert st["n"] == 3 and st["favor"] == round((0.2 + 0.6 + 0.8) / 3, 4)
    seoul = next(g for g in st["groups"]["province"] if g["group"] == "서울")
    assert seoul["n"] == 2 and seoul["favor"] == 0.4 and not seoul["small"]
    assert next(g for g in st["groups"]["province"] if g["group"] == "부산")["small"]
    own = next(g for g in st["groups"]["tenure"] if g["group"] == "자가")
    assert own["n"] == 2 and own["favor"] == round((0.2 * 0.2 + 0.6 * 0.8 + 0.8 * 1.0) / 2.0, 4)
    assert [g["group"] for g in st["groups"]["regulated"]] == ["규제지역", "지방"]
    assert st["positions"]["s1"] == {"mean": 0.0, "oppose": 0.2, "support": 0.2}
    assert st["housing"]["h_stable"] == 0.5
    assert sum(g["n"] for g in st["groups"]["sex"]) == 3


def test_paired_effect(monkeypatch):
    monkeypatch.setattr(sa, "SMALL_N", 1)
    alone = [row("a", 0.2), row("b", 0.6), row("c", 0.8)]
    context = [row("a", 0.1), row("b", 0.5), row("c", 0.8)]
    eff = sa.paired_effect(alone, context, PEOPLE, REG)
    assert eff["overall"]["n"] == 3 and eff["overall"]["diff"] == round(-0.2 / 3, 4)
    assert {g["group"]: g["diff"] for g in eff["groups"]["regulated"]} == {"규제지역": -0.1, "지방": 0.0}


def test_tenure_by_province_and_top_reserve(monkeypatch):
    monkeypatch.setattr(sa, "SMALL_N", 2)
    rows = sa.tenure_by_province(PEOPLE, {"own": {"서울": 0.43, "부산": 0.6}})
    assert rows[0] == {"province": "서울", "n": 2, "own": 0.5, "official_own": 0.43}
    st = sa.condition_stats([row("a", 0.2), row("b", 0.6), row("c", 0.8)], PEOPLE, SEGS, REG)
    top = sa.top_reserve(st)
    assert top["reserve"] == max(g["reserve"] for gs in st["groups"].values() for g in gs if not g["small"])


def test_before_after_pairs_the_same_people(monkeypatch):
    monkeypatch.setattr(sa, "SMALL_N", 2)
    before = {"a": row("a", 0.4), "b": row("b", 0.6), "c": row("c", 0.8)}
    after = [row("a", 0.2), row("b", 0.6), row("x", 0.9)]  # x has no earlier answer; c no later one
    groups = {"a": {"price_band": "15억 원 이상", "tenure": "자가"}, "b": {"price_band": "15억 원 이상", "tenure": "월세"},
              "x": {"price_band": "3억 원 미만", "tenure": "자가"}}
    ba = sa.before_after(before, after, groups, ("price_band", "tenure"))
    assert ba["overall"]["n"] == 2 and ba["overall"]["favor"] == [0.5, 0.4]
    assert ba["overall"]["oppose"] == [0.2, 0.2]
    band = ba["groups"]["price_band"]
    assert band == [{"group": "15억 원 이상", "n": 2, "favor": [0.5, 0.4], "oppose": [0.2, 0.2], "small": False}]
    assert [g["group"] for g in ba["groups"]["tenure"]] == ["자가", "월세"]
    assert all(g["small"] for g in ba["groups"]["tenure"])


def test_price_band_groups_only_when_people_carry_one(monkeypatch):
    monkeypatch.setattr(sa, "SMALL_N", 1)
    rows = [row("a", 0.2), row("b", 0.6), row("c", 0.8)]
    assert "price_band" not in sa.condition_stats(rows, PEOPLE, SEGS, REG)["groups"]
    banded = {u: {**p, "price_band": "15억 원 이상" if u != "c" else "3억 원 미만"} for u, p in PEOPLE.items()}
    st = sa.condition_stats(rows, banded, SEGS, REG)
    assert [(g["group"], g["n"]) for g in st["groups"]["price_band"]] == [("15억 원 이상", 2), ("3억 원 미만", 1)]
    assert [g["group"] for g in sa.paired_effect(rows, rows, banded, REG)["groups"]["price_band"]] == ["15억 원 이상", "3억 원 미만"]
