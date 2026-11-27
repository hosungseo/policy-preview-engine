from pp import survey_match as sm

P = {"uuid": "u-1", "sex": "여자", "age": 34, "province": "경상북", "education_level": "4년제 대학교",
     "marital_status": "배우자있음", "family_type": "배우자·자녀와 거주", "housing_type": "아파트", "occupation": "간호사"}
A = {"income": "50_70", "employment": "wage", "nonregular": False, "tenure": "jeonse", "disability": False}


def test_member_reads_common_kosis_labels():
    yes = ["여성", "30대", "30~39세", "30-39세", "만30세-34세", "30대 이하", "20세 이상", "대졸 이상", "대재 이상", "기혼",
           "3인 이상", "경북", "경상북도", "대경권", "비수도권", "임금근로자", "상용근로자", "정규직", "아파트", "전세", "취업자"]
    no = ["남성", "40대", "60세 이상", "고졸", "미혼", "1인", "서울", "수도권", "비정규직", "자영업자", "단독주택", "장애인", "무직"]
    for label in yes:
        assert sm.member(label, P, A) is True, label
    for label in no:
        assert sm.member(label, P, A) is False, label
    for label in ("전체", "대도시", "학생", "중학교 1학년", "4인", "기타"):
        assert sm.member(label, P, A) is None, label


def test_income_point_stays_inside_the_band_and_is_stable():
    hits = [lab for lab in ("100만원 미만", "100~200만원", "200~300만원", "300~400만원", "400~500만원", "500~600만원",
                            "600만원 이상") if sm.member(lab, P, A)]
    assert len(hits) == 1 and hits[0] in ("400~500만원", "500~600만원")
    assert sm.member(hits[0], P, A) is True
    assert sm.member("연 5000만원 이상", P, A) is True and sm.member("연 7000만원 이상", P, A) is False


def test_labels_from_newer_tables():
    from pp import survey_match as sm
    p = {"uuid": "a", "sex": "남자", "age": 55, "education_level": "4년제 대학교", "marital_status": "이혼",
         "family_type": "혼자 거주", "province": "경기", "occupation": "교사"}
    a = {"income": "30_50", "employment": "self_alone", "disability": True}
    assert sm.member("50세 이상~60세 미만", p, a) and not sm.member("60세 이상~70세 미만", p, a)
    assert sm.member("배우자 없음", p, a) and sm.member("이혼 또는 별거", p, a)
    assert sm.member("인천·경기", p, a) and not sm.member("대구·경북", p, a)
    assert sm.member("대학교(4년제 이상)", p, a) and sm.member("고용원없는자영자", p, a)
    assert sm.member("장애 있음", p, a) and sm.member("노인독거", p, a) is False
