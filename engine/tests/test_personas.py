import pytest

from pp import config, personas


def test_connect_missing_raises(tmp_path):
    with pytest.raises(config.DataMissing):
        personas.connect(tmp_path / "nope.db")


def test_index_and_strata(persona_db):
    conn = personas.connect()
    index = personas.PersonaIndex.load(conn)
    assert len(index.ids) == 170
    strata = index.strata()
    assert 1 in strata[("서울", "19–29세", "남자")]
    assert sum(len(v) for v in strata.values()) == 170


def test_fetch_keeps_order_and_extracts_name(persona_db):
    conn = personas.connect()
    rows = personas.fetch(conn, [3, 1])
    assert [r["id"] for r in rows] == [3, 1]
    assert rows[0]["name"] == "박지영"
    assert rows[1]["name"] == "김영숙"
    assert rows[0]["province"] == "대구"


def test_filter_ids(persona_db):
    conn = personas.connect()
    taxi = personas.filter_ids(conn, {"occupation_like": ["택시"]})
    assert len(taxi) == 17
    older = personas.filter_ids(conn, {"occupation_like": ["택시"], "age_min": 60})
    assert older and set(older) < set(taxi)
    seoul = personas.filter_ids(conn, {"province_in": ["서울"]})
    assert len(seoul) == 10
    assert personas.filter_ids(conn, {}) == []
    capped = personas.filter_ids(conn, {"age_min": 19}, limit=20)
    assert len(capped) == 20
    with pytest.raises(ValueError):
        personas.filter_ids(conn, {"income_min": 1})


def test_usable_keywords_and_fts(persona_db):
    assert personas.usable_keywords(['"지하철로"', "택시", "지하철로", "버스를"]) == ["지하철로", "택시", "버스를"]
    conn = personas.connect()
    assert len(personas.fts_ids(conn, ["지하철로"])) == 57
    assert len(personas.fts_ids(conn, ["택시"])) == 17


def test_short_search_is_literal_and_uses_every_indexed_column(persona_db):
    import sqlite3
    with sqlite3.connect(persona_db) as conn:
        conn.execute("UPDATE persona SET sports_persona='월세 50% A_ OR 돌봄' WHERE id=2")
        conn.execute("INSERT INTO persona_fts(persona_fts) VALUES ('rebuild')")
    conn = personas.connect()
    for keyword in ("월세", "50%", "A_", "OR", "돌봄"):
        assert 2 in personas.fts_ids(conn, [keyword])
    assert personas.fts_ids(conn, ["월%", "월_", "없는단어"]) == []
    assert personas.fts_ids(conn, ["월세"], limit=0) == []
    mixed = personas.fts_ids(conn, ["지하철로", "월세"], limit=2)
    assert len(mixed) == len(set(mixed)) == 2 and 2 in mixed


def test_occupation_names_are_current_jobs_in_the_db(persona_db):
    import sqlite3
    with sqlite3.connect(persona_db) as w:
        w.execute("INSERT INTO persona (id, uuid, occupation, province, age, sex) "
                  "VALUES (999, 'u00999', '전직 택시 운전원, 현재 구직중', '서울', 40, '남자')")
    names = personas.occupation_names(personas.connect())
    assert len(names) == 10 and names == sorted(names)
    assert "택시 운전원" in names and not any(n.startswith("전직 ") for n in names)


def test_listed_occupation_names_match_exactly(persona_db):
    import sqlite3
    with sqlite3.connect(persona_db) as w:
        for pid, occ in ((901, "검사"), (902, "전직 검사, 현재 구직중"), (903, "환경 검사원")):
            w.execute("INSERT INTO persona (id, uuid, occupation, province, age, sex) VALUES (?, ?, ?, '서울', 40, '남자')",
                      (pid, f"u{pid:05d}", occ))
    conn = personas.connect()
    assert sorted(personas.filter_ids(conn, {"occupation_like": ["검사"]})) == [901, 902]  # a real name: exact
    assert personas.filter_ids(conn, {"occupation_like": ["검사원"]}) == [903]  # not a name: substring
    assert len(personas.filter_ids(conn, {"occupation_like": ["택시", "검사"]})) == 17 + 2


def test_ids_for_uuids(persona_db):
    conn = personas.connect()
    assert personas.ids_for_uuids(conn, ["u00003", "u00001", "missing"]) == [3, 1]
    absent = []
    assert personas.ids_for_uuids(conn, ["u00003", "missing"], missing=absent) == [3]
    assert absent == ["missing"]
    with pytest.raises(ValueError, match="missing"):
        personas.ids_for_uuids(conn, ["u00003", "missing"], strict=True)


def test_filter_receipt_distinguishes_sorted_results_from_seeded_sample(persona_db):
    conn = personas.connect()
    full, sampled, repeated = {}, {}, {}
    all_ids = personas.filter_ids(conn, {"age_min": 19}, limit=200, receipt=full)
    ids = personas.filter_ids(conn, {"age_min": 19}, limit=12, seed=7, receipt=sampled)
    assert ids == personas.filter_ids(conn, {"age_min": 19}, limit=12, seed=7, receipt=repeated)
    assert sampled == repeated and sampled["matching_count"] == full["matching_count"] == 170
    assert all_ids == sorted(all_ids) and ids == sorted(ids)
    assert full["sampling"] == "none" and full["sampled"] is False and full["seed"] is None
    assert sampled["sampling"] == "seeded_random_without_replacement" and sampled["seed"] == 7
    assert sampled["parameters"]["age_min"] == 19 and sampled["returned_count"] == 12


@pytest.mark.parametrize("group", [
    {"age_min": 65, "has_smartphone": "없음"},
    {"age_min": 65, "province_in": ["존재하지않는지역"]},
    {"age_min": 65, "sex": None}, [],
])
def test_direct_filter_never_weakens_conditions(persona_db, group):
    with pytest.raises(ValueError):
        personas.filter_ids(personas.connect(), group)


def test_population(persona_db):
    pop = personas.population(personas.connect())
    assert pop["total"] == 170
    assert sum(pop["region"].values()) == 170
    assert sum(pop["family"].values()) == 170
    assert set(pop["age_band"]) <= {b[2] for b in config.AGE_BANDS}
