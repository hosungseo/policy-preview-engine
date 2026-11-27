import json

import pytest

from pp import hearing, llm, pipeline, prompts

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


@pytest.mark.parametrize("size", [899, 900, 901])
def test_hearing_records_exact_prompt_excerpt_and_truncation(monkeypatch, size):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    people, reactions, _ = fixture(1)
    original, sent = llm.complete_json, []

    def capture(task, system, prompt, **kwargs):
        if task == "hearing":
            sent.append(prompt.split("[정책 요약]\n")[1].split("\n\n[안건]")[0])
        return original(task, system, prompt, **kwargs)

    monkeypatch.setattr(llm, "complete_json", capture)
    policy = "가" * size
    result = hearing.run_hearing("시험", policy, ["u1"], people, {"u1": reactions[0]}, ["시험"], workers=1)
    assert result["policy_truncated"] is (size > 900)
    assert result["total_chars"] == size and result["shown_chars"] == min(size, 900)
    assert sent == [result["policy_excerpt"]] * 3
    assert result["policy_excerpt"] == prompts.clip(policy, 900)
    if size > 900:
        assert "뒤의 조항" in result["context_note"]


def test_context_counts_whitespace_as_actually_shown():
    context = prompts.hearing_policy_context("  가\n\n나\t 다  ")
    assert context["policy_truncated"] is False and context["policy_excerpt"] == "가 나 다"
    assert context["shown_chars"] == context["total_chars"] == 5
    assert context["original_chars"] > context["total_chars"]


def test_hearing_stage_records_truncation_in_meta(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_LLM_PROVIDER", "mock")
    text = "앞" * 905 + "뒤에서만 나오는 예외조항"
    policy = tmp_path / "input.json"
    policy.write_text(json.dumps({"id": "long", "title": "시험", "kind": "가상", "text": text}))
    job = pipeline.Run(policy, run_dir=tmp_path / "run")
    people, reactions, issues = fixture(1)
    for name, data in (("personas.json", list(people.values())), ("reactions.json", reactions),
                       ("analysis.json", {"issues": issues})):
        job.path(name).write_text(json.dumps(data))
    job.stage_hearing()
    result = json.loads(job.path("hearing.json").read_text())
    meta = json.loads(job.path("meta.json").read_text())["hearing_context"]
    assert result["policy_truncated"] and meta["policy_truncated"]
    assert meta == prompts.hearing_policy_context(text)
    assert "뒤에서만 나오는 예외조항" not in meta["policy_excerpt"]
