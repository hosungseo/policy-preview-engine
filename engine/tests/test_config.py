from pp import config


def test_age_band_boundaries():
    assert config.age_band(19) == "19–29세"
    assert config.age_band(29) == "19–29세"
    assert config.age_band(30) == "30대"
    assert config.age_band(69) == "60대"
    assert config.age_band(70) == "70세 이상"
    assert config.age_band(99) == "70세 이상"


def test_family_bucket():
    cases = {
        "혼자 거주": "1인 가구", "혼자 거주 (배우자 별거)": "1인 가구", "배우자와 거주": "부부",
        "배우자·자녀와 거주": "부부+자녀", "배우자·자녀·어머니와 거주": "부부+자녀",
        "배우자·편부모와 거주": "기타", "자녀와 거주 (한부모)": "배우자 없이 자녀와 거주",
        "자녀와 거주 (배우자 별거)": "배우자 없이 자녀와 거주",
        "자녀·어머니와 거주": "배우자 없이 자녀와 거주", "부모와 동거": "부모 등과 동거",
        "어머니와 동거": "부모 등과 동거", "조부 또는 조모와 동거": "부모 등과 동거",
        "손자녀와 거주": "기타", "형제 부부 가구에 동거": "기타", "기타2세대": "기타",
    }
    for raw, bucket in cases.items():
        assert config.family_bucket(raw) == bucket, raw


def test_family_buckets_name_composition_not_eligibility():
    # A household bucket must not read as a benefit group such as 한부모가족; old saved labels map to the new name.
    assert all("한부모" not in b for b in config.FAMILY_BUCKETS)
    assert set(config.LEGACY_FAMILY_LABELS.values()) <= set(config.FAMILY_BUCKETS)
    assert "가구 구성" in config.FAMILY_NOTE and "지원 대상" in config.FAMILY_NOTE


def test_to_raw_province():
    assert config.to_raw_province("경상북") == "경상북"
    assert config.to_raw_province("경북") == "경상북"
    assert config.to_raw_province("경상북도") == "경상북"
    assert config.to_raw_province("전라북도") == "전북"
    assert config.to_raw_province("전북특별자치도") == "전북"
    assert config.to_raw_province("서울특별시") == "서울"
    assert config.to_raw_province("충북") == "충청북"
    assert config.to_raw_province("화성시") is None


def test_every_province_has_region_and_display():
    assert set(config.REGION_OF) == set(config.PROVINCE_DISPLAY)
    assert set(config.REGION_OF.values()) == set(config.REGIONS)


def test_paths_follow_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("PP_PERSONA_DB", raising=False)
    assert config.persona_db() == tmp_path / "vendor" / "korean-people-persona" / "database" / "persona.db"
    assert config.occupation_cache(mock=True).name == "occupation_major.mock.json"
    assert config.llm_cwd().is_dir()


def test_series_dirs_follow_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PP_WEB_SERIES_DIR", str(tmp_path / "pub"))
    monkeypatch.setenv("PP_WEB_DEV_SERIES_DIR", str(tmp_path / "dev"))
    assert config.web_series_dir() == tmp_path / "pub"
    assert config.web_dev_series_dir() == tmp_path / "dev"
