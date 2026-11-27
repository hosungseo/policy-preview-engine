from pp import prompts, voice

PERSON = {
    "name": "김영숙", "sex": "여자", "age": 74, "district": "경북-안동시", "province": "경상북",
    "occupation": "곡물 재배자", "education_level": "초등학교", "marital_status": "사별",
    "family_type": "혼자 거주", "housing_type": "단독주택",
    "persona": "김영숙 씨는 " + "가" * 400, "professional_persona": "논농사를 짓습니다.",
    "family_persona": "혼자 삽니다.", "cultural_background": "안동에서 자랐습니다.",
}


def test_voice_guide_by_age_and_education():
    old = voice.voice_guide(PERSON)
    assert "짧고" in old and "전문 용어" in old and "사투리" in old
    young = voice.voice_guide({**PERSON, "age": 25, "education_level": "4년제 대학교"})
    assert "구어체" in young and "전문 용어" not in young


def test_persona_profile_display_and_clip():
    long = prompts.persona_profile(PERSON)
    assert "경북-안동시 (경북)" in long and "논농사를 짓습니다." in long
    assert max(len(line) for line in long.splitlines()) <= 300
    short = prompts.persona_profile(PERSON, long=False)
    assert "논농사" not in short


def test_react_prompt_structure():
    p = prompts.react_prompt(PERSON, "  1. 정책 내용입니다.  ")
    assert "[정책]\n1. 정책 내용입니다.\n[/정책]" in p
    assert '{"support": 0' in p and "{{" not in p


def test_target_prompt_lists_real_occupation_names():
    p = prompts.target_prompt("정책", ["간호사", "택시 운전원"])
    assert "[직업명 목록]\n간호사, 택시 운전원\n[/직업명 목록]" in p
    assert "[직업명 목록]의 이름을 그대로" in p and "[정책]\n정책\n[/정책]" in p
    assert "[직업명 목록]" not in prompts.target_prompt("정책")


def test_other_prompts_have_parseable_markers():
    assert "경북" in prompts.target_prompt("정책") and "3글자 이상" in prompts.target_prompt("정책")
    assert "\n- 택시 운전원\n" in prompts.occupation_prompt(["택시 운전원", "무직"])
    cand = {"group": "농림어업 숙련 종사자", "n": 12, "direct": 0.5, "oppose": 0.4, "silent": 0.9, "channels": ["경로당"]}
    block = prompts.outreach_block(cand, ["너무 어렵네요."])
    assert block.startswith("## 그룹: 농림어업 숙련 종사자\n") and "직접 영향 50%" in block
    assert "r1|지지 -1|" in prompts.cluster_prompt("정책", "r1|지지 -1|이유", 3, 8)
    assert "i1|" in prompts.qa_prompt("정책", "i1|쟁점|요약")
    hp = prompts.hearing_prompt(PERSON, "정책 본문", ["쟁점 A"], {"support": -1, "reason": "부담돼요"}, "", 2)
    assert "이름으로 부르며" in hp and "(아직 없음)" in hp
