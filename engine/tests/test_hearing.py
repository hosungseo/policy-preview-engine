from pp import hearing

PROVS = ["서울", "부산", "경상북", "전라남", "강원", "제주", "대전", "경기"]


def fixture(n=16):
    people, reactions = {}, []
    for i in range(1, n + 1):
        uuid = f"u{i}"
        people[uuid] = {"uuid": uuid, "name": f"사람{i}", "sex": "남자", "age": 20 + (i * 7) % 60,
                        "province": PROVS[i % len(PROVS)], "district": "구", "occupation": f"직업{i}",
                        "education_level": "고등학교", "marital_status": "미혼", "family_type": "혼자 거주",
                        "housing_type": "아파트", "persona": ""}
        reactions.append({"rid": f"r{i}", "uuid": uuid, "support": (i % 5) - 2, "reason": f"이유 {i}"})
    issues = [{"title": f"쟁점{k}", "member_ids": [f"r{i}" for i in range(k, n + 1, 3)]} for k in (1, 2, 3)]
    return people, reactions, issues


def test_select_participants_is_deterministic_and_balanced():
    people, reactions, issues = fixture()
    one = hearing.select_participants(issues, reactions, people, k=6)
    two = hearing.select_participants(issues, reactions, people, k=6)
    assert one == two and len(one) == 6 and len(set(one)) == 6
    sup = {r["uuid"]: r["support"] for r in reactions}
    assert sum(sup[u] > 0 for u in one) >= 2 and sum(sup[u] < 0 for u in one) >= 2



def test_select_participants_seats_reserved_voices_when_nobody_opposes():
    people, reactions, issues = fixture()
    for r in reactions:  # everyone in favour except one neutral voice
        r["support"] = max(1, r["support"])
    reactions[-1]["support"] = 0
    chosen = hearing.select_participants(issues, reactions, people, k=6)
    assert reactions[-1]["uuid"] in chosen

def test_run_hearing_with_mock(monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    people, reactions, issues = fixture()
    parts = hearing.select_participants(issues, reactions, people, k=6)
    result = hearing.run_hearing("무임승차 정책", "정책 본문", parts, people,
                                 {r["uuid"]: r for r in reactions}, ["쟁점1", "쟁점2"], workers=3)
    turns = result["turns"]
    assert len(turns) == 1 + 6 + 1 + 6 + 1 + 6
    assert turns[0]["speaker"] == "사회자" and turns[0]["round"] == 0
    assert [t["round"] for t in turns if t["speaker"] != "사회자"] == [1] * 6 + [2] * 6 + [3] * 6
    assert set(result["summary"]) == {"agreements", "disagreements", "missing"}


def test_render_transcript_names_speakers():
    people, reactions, _ = fixture(2)
    text = hearing.render_transcript([{"round": 0, "speaker": "사회자", "text": "시작합니다."},
                                      {"round": 1, "speaker": "u1", "text": "반대합니다."}], people)
    assert text.splitlines() == ["사회자: 시작합니다.", "사람1(27세·직업1): 반대합니다."]
