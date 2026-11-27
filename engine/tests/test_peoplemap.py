import json

import numpy as np
import pytest

from pp import dotmap, peoplemap, personas


def fake_place(districts, b, seed=0, jitter=0):
    n = sum(c for _, c in districts)
    table, pos = [], 0
    for d, c in districts:
        table.append({"d": d, "s": pos, "n": c, "cx": 1.0, "cy": 2.0})
        pos += c
    return np.arange(n, dtype=float) % 50, np.arange(n, dtype=float) // 50, table


@pytest.fixture
def setup(persona_db, tmp_path, monkeypatch):
    monkeypatch.setattr(dotmap, "place", fake_place)
    monkeypatch.setattr(dotmap, "extent", lambda b: (100.0, 120.0))
    monkeypatch.setattr(dotmap, "outlines", lambda b: {"sido": [], "seoul": []})
    conn = personas.connect()
    uuids = [f"u{i:05d}" for i in (5, 1, 42, 170, 99)]          # panel order is not DB order
    run = tmp_path / "run"
    (run / "answers").mkdir(parents=True)
    (run / "panel.json").write_text(json.dumps({"people": [{"uuid": u} for u in uuids]}), encoding="utf-8")
    (run / "tenure.jsonl").write_text("\n".join(json.dumps({"uuid": u, "assigned": a, "multi_home": m}) for u, a, m in
                                                 zip(uuids, ["own", "jeonse", "monthly", "own", "free"],
                                                     [True, None, None, False, None])), encoding="utf-8")
    favs = {"m1": [0.61, 0.40, 0.55, 0.70, 0.20], "m2": [0.10, 0.90, 0.33, 0.52, 0.47]}
    for mid, fs in favs.items():
        rows = [{"uuid": u, "favor": f, "stance_probs": [0.05, 0.1, round(0.85 - f, 2), f, 0.0]} for u, f in zip(uuids, fs)]
        (run / "answers" / f"{mid}__alone.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    bundle = {"id": "housing", "measures": [
        {"id": mid, "short": s, "date": d, "title": t, "agency": "가", "conditions": {"alone": {"favor": float(np.mean(fs))}}}
        for (mid, fs), s, d, t in zip(favs.items(), ["1·1", "2·2"], ["2025-01-01", "2025-02-02"], ["첫 대책", "둘째 대책"])]}
    bpath = tmp_path / "bundle.json"
    bpath.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return conn, run, bpath, uuids, favs, tmp_path / "out"


def test_build_writes_dots_panel_people_and_meta(setup):
    conn, run, bpath, uuids, favs, out = setup
    summary = peoplemap.build(run, bpath, out, out, conn=conn, boundaries=dotmap.Boundaries([], [], []))
    assert summary == {"dots": 170, "panel": 5, "measures": 2, "files": 4}
    assert (out / "dots.bin").stat().st_size == 170 * 4
    raw = (out / "panel.bin").read_bytes()
    n, m = 5, 2
    assert len(raw) == n * 4 + n + 2 * m * n
    idx = np.frombuffer(raw[: n * 4], "<u4")
    ten = np.frombuffer(raw[n * 4: n * 5], np.uint8)
    fav = np.frombuffer(raw[n * 5: n * 5 + m * n], np.uint8).reshape(m, n)
    opp = np.frombuffer(raw[n * 5 + m * n:], np.uint8).reshape(m, n)
    # each dot index points at that person's slot in DB order (district, id)
    _, ids = peoplemap.district_counts(conn)
    assert [int(ids[i]) for i in idx] == personas.ids_for_uuids(conn, uuids)
    assert ten.tolist() == [4, 1, 2, 0, 3]
    assert fav[0].tolist() == [61, 40, 55, 70, 20] and fav[1].tolist() == [10, 90, 33, 52, 47]
    assert opp.tolist() == [[15] * 5, [15] * 5]
    people = json.loads((out / "people-00.json").read_text(encoding="utf-8"))
    card = personas.fetch(conn, personas.ids_for_uuids(conn, [uuids[0]]))[0]
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    d, age, sex, occ, fam, house, text = people[0]
    assert meta["districts"][d]["k"] == card["district"] and age == card["age"] and occ == card["occupation"]
    assert sex == (0 if card["sex"] == "남자" else 1) and fam == card["family_type"] and house == card["housing_type"]
    assert text == card["persona"]
    assert meta["panel"] == {"n": 5, "m": 2, "chunk": peoplemap.CHUNK, "files": ["people-00.json"], "condition": "alone"}
    assert [x["short"] for x in meta["measures"]] == ["1·1", "2·2"]
    assert meta["n_dots"] == 170 and meta["sizes"]["dots.bin"] == 680
    assert sum(x["n"] for x in meta["districts"]) == 170
    # The map's files travel with their credit: personas (CC BY 4.0, changed), boundaries (KOGL type 1), model output.
    from pp import attribution
    assert attribution.validate(meta["attribution"]) == []
    roles = [s["role"] for s in meta["attribution"]["sources"]]
    assert roles == ["synthetic_personas", "boundaries", "generated"]
    assert "공공누리 제1유형" in meta["attribution"]["notice"] and "지원 대상" in meta["field_notes"]["family"]


def test_build_refuses_a_bundle_from_another_run(setup):
    conn, run, bpath, *_ , out = setup
    bundle = json.loads(bpath.read_text(encoding="utf-8"))
    bundle["measures"][0]["conditions"]["alone"]["favor"] += 0.05
    bpath.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(peoplemap.PeopleMapError):
        peoplemap.build(run, bpath, out, out, conn=conn, boundaries=dotmap.Boundaries([], [], []))


def test_display_and_first_sentence():
    assert peoplemap.display("경상북-포항시 남구") == "경북 포항시 남구"
    assert peoplemap.display("서울-노원구") == "서울 노원구"
    assert peoplemap.first_sentence("가 씨는 교사입니다. 둘째 문장입니다.") == "가 씨는 교사입니다."
    assert peoplemap.first_sentence("끝없는" * 60).endswith("…")
