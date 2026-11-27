import pytest

from pp import panel, personas


def test_allocate_proportional_and_sums():
    assert panel.allocate({"a": 50, "b": 30, "c": 20}, 10) == {"a": 5, "b": 3, "c": 2}
    assert panel.allocate({"a": 1, "b": 1, "c": 1}, 2) == {"a": 1, "b": 1, "c": 0}
    assert sum(panel.allocate({"a": 3, "b": 4}, 100).values()) == 7
    assert panel.allocate({"a": 0}, 5) == {"a": 0}


def test_sample_representative_is_deterministic(persona_db):
    strata = personas.PersonaIndex.load(personas.connect()).strata()
    one = panel.sample_representative(strata, 40, seed=1)
    two = panel.sample_representative(strata, 40, seed=1)
    other = panel.sample_representative(strata, 40, seed=2)
    assert one == two
    assert len(one) == 40 and len(set(one)) == 40
    assert one != other


def test_normalize_spec_cleans_and_maps_provinces():
    spec = panel.normalize_spec({
        "filters": [
            {"occupation_like": "택시", "province_in": ["경북", "전라북도"]},
        ],
        "keywords": ["지하철로", "", "택시"],
        "semantic_query": " 지하철로 출퇴근하는 노인 ",
    })
    assert spec["filters"] == [{"occupation_like": ["택시"], "province_in": ["경상북", "전북"]}]
    assert spec["keywords"] == ["지하철로", "택시"]
    assert spec["semantic_query"] == "지하철로 출퇴근하는 노인"
    assert panel.normalize_spec({"keywords": ["택시"]})["keywords"] == ["택시"]
    with pytest.raises(ValueError):
        panel.normalize_spec({"keywords": ["집"]})


@pytest.mark.parametrize("group, message", [
    ({"age_min": 65, "has_smartphone": "없음"}, "unknown filter keys"),
    ({"age_min": 65, "province_in": ["존재하지않는지역"]}, "unknown provinces"),
    ({"age_min": 65, "province_in": ["서울", "화성시"]}, "unknown provinces"),
    ({"age_min": 65, "sex": "모름"}, "sex must"),
    ({"age_min": 65, "province_in": []}, "non-empty strings"),
    ({"age_min": 65, "occupation_like": None}, "non-empty strings"),
    ({"age_min": "65"}, "integer"),
    ({"age_min": 65, "age_max": 20}, "must not exceed"),
    ({}, "non-empty object"),
    ("not a dict", "non-empty object"),
])
def test_normalize_spec_never_discards_requested_conditions(group, message):
    # The first two are the two zero-cost reproductions in the public code review.
    with pytest.raises(ValueError, match=message):
        panel.normalize_spec({"filters": [group], "keywords": ["지하철로"], "semantic_query": "노인"})


def test_normalize_spec_rejects_excess_groups_and_top_level_conditions():
    with pytest.raises(ValueError, match="four groups"):
        panel.normalize_spec({"filters": [{"age_min": 65}] * 5})
    with pytest.raises(ValueError, match="unknown targeting keys"):
        panel.normalize_spec({"filters": [{"age_min": 65}], "has_smartphone": False})


def test_diversify_caps_occupation():
    cands = [{"id": i, "province": "서울", "age": 30 + i % 40, "occupation": "택시 운전원", "found_by": ["filter"]}
             for i in range(20)]
    cands += [{"id": 100 + i, "province": "부산", "age": 40, "occupation": f"직업{i}", "found_by": ["fts"]}
              for i in range(10)]
    picked = panel.diversify(cands, 12, max_per_occupation=5)
    assert len(picked) == 12
    assert sum(c["occupation"] == "택시 운전원" for c in picked) <= 5


def _diversify_before_relaxing(cands, k, max_per_occupation=5, seed=42):
    """The selection as it was before the cap could relax (2026-09-24), kept as a reference."""
    import random
    from collections import defaultdict
    from pp import config
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for cand in cands:
        buckets[(config.REGION_OF[cand["province"]], config.age_band(cand["age"]))].append(cand)
    for items in buckets.values():
        rng.shuffle(items)
        items.sort(key=lambda c: -len(c["found_by"]))
    keys = sorted(buckets, key=str)
    rng.shuffle(keys)
    per_occupation = defaultdict(int)
    picked = []
    while len(picked) < k and any(buckets[key] for key in keys):
        for key in keys:
            if len(picked) >= k:
                break
            items = buckets[key]
            while items:
                cand = items.pop(0)
                if per_occupation[cand["occupation"]] < max_per_occupation:
                    per_occupation[cand["occupation"]] += 1
                    picked.append(cand)
                    break
    return picked


def _cands(n_occupations, per_occupation):
    provinces = ["서울", "부산", "전라남", "경기", "제주"]
    return [{"id": o * 1000 + i, "province": provinces[(o + i) % 5], "age": 20 + (o * 7 + i * 3) % 60,
             "occupation": f"직업{o}", "found_by": ["filter", "fts"][: 1 + (i % 2)]}
            for o in range(n_occupations) for i in range(per_occupation)]


def test_diversify_unchanged_when_the_cap_fills_the_panel():
    cands = _cands(30, 8)
    new = panel.diversify([dict(c) for c in cands], 100)
    old = _diversify_before_relaxing([dict(c) for c in cands], 100)
    assert len(new) == 100 and [c["id"] for c in new] == [c["id"] for c in old]


def test_diversify_relaxes_the_cap_when_few_occupations_are_affected():
    cands = _cands(4, 30)  # a narrow policy: only four jobs are affected
    picked = panel.diversify(cands, 60)
    counts = {}
    for c in picked:
        counts[c["occupation"]] = counts.get(c["occupation"], 0) + 1
    assert len(picked) == 60 and len({c["id"] for c in picked}) == 60
    assert max(counts.values()) - min(counts.values()) <= 5  # raised in steps, so still spread
    assert len(_diversify_before_relaxing(_cands(4, 30), 60)) == 20  # the old cap stopped at 4 x 5
    assert len(panel.diversify(_cands(2, 3), 60)) == 6  # never more than there are


def test_interleave_gives_every_filter_group_a_share():
    assert panel.interleave([[1, 2, 3, 4], [9, 2], [7]]) == [1, 9, 7, 2, 3, 4]
    assert panel.interleave([]) == []


def test_build_affected(persona_db):
    conn = personas.connect()
    spec = panel.normalize_spec({"filters": [{"occupation_like": ["택시"]}], "keywords": ["지하철로"], "semantic_query": ""})
    picked, stats = panel.build_affected(conn, spec, exclude={1, 11}, k=15)
    assert 0 < len(picked) <= 15
    assert all(c["id"] not in {1, 11} for c in picked)
    assert stats == {"filter": 17, "fts": 57, "semantic": 0}
    assert all(set(c["found_by"]) <= {"filter", "fts", "semantic"} and c["found_by"] for c in picked)


def test_build_affected_revalidates_and_records_zero_matches(persona_db):
    conn = personas.connect()
    with pytest.raises(ValueError, match="unknown provinces"):
        panel.build_affected(conn, {"filters": [{"age_min": 65, "province_in": ["없는곳"]}]}, set())
    receipt = {}
    picked, counts = panel.build_affected(conn, {"filters": [{"age_min": 999}]}, set(), receipt=receipt)
    assert picked == [] and counts == {"filter": 0, "fts": 0, "semantic": 0}
    assert receipt["filter_groups"][0]["matching_count"] == 0
    assert receipt["selected_count"] == receipt["candidate_count"] == 0
