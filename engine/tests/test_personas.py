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
    assert personas.usable_keywords(['"지하철로"', "택시", "지하철로", "버스를"]) == ["지하철로", "버스를"]
    conn = personas.connect()
    assert len(personas.fts_ids(conn, ["지하철로"])) == 57
    assert personas.fts_ids(conn, ["택시"]) == []


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


def test_population(persona_db):
    pop = personas.population(personas.connect())
    assert pop["total"] == 170
    assert sum(pop["region"].values()) == 170
    assert sum(pop["family"].values()) == 170
    assert set(pop["age_band"]) <= {b[2] for b in config.AGE_BANDS}
