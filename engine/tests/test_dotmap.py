import numpy as np
import pytest
import shapely
from shapely.geometry import shape

from pp import dotmap


def square(lon0, lat0, size):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + size, lat0], [lon0 + size, lat0 + size],
                                                [lon0, lat0 + size], [lon0, lat0]]]}


def feature(props, geom):
    return {"type": "Feature", "properties": props, "geometry": geom}


@pytest.fixture
def bounds():
    # two Seoul districts; 화성시 split into two 구 whose new codes the 읍면동 do not carry yet
    sigg = [feature({"sig_cd": "11110", "full_nm": "서울특별시 가구", "sig_kor_nm": "가구"}, square(127.0, 37.5, 0.10)),
            feature({"sig_cd": "11140", "full_nm": "서울특별시 나구", "sig_kor_nm": "나구"}, square(127.1, 37.5, 0.10)),
            feature({"sig_cd": "41591", "full_nm": "경기도 화성시 동탄구", "sig_kor_nm": "동탄구"}, square(127.0, 37.2, 0.10)),
            feature({"sig_cd": "41593", "full_nm": "경기도 화성시 만세구", "sig_kor_nm": "만세구"}, square(127.1, 37.2, 0.10))]
    emd = [feature({"emd_cd": "11110101", "full_nm": "서울특별시 가구 갑동", "emd_kor_nm": "갑동"}, square(127.0, 37.5, 0.05)),
           feature({"emd_cd": "11110102", "full_nm": "서울특별시 가구 을동", "emd_kor_nm": "을동"}, square(127.05, 37.55, 0.05)),
           feature({"emd_cd": "11140101", "full_nm": "서울특별시 나구 병동", "emd_kor_nm": "병동"}, square(127.1, 37.5, 0.10)),
           feature({"emd_cd": "41590101", "full_nm": "경기도 화성시 동탄구 정면", "emd_kor_nm": "정면"}, square(127.0, 37.2, 0.10)),
           feature({"emd_cd": "41590102", "full_nm": "경기도 화성시 만세구 무읍", "emd_kor_nm": "무읍"}, square(127.1, 37.2, 0.10))]
    sido = [feature({"ctprvn_cd": "11", "ctp_kor_nm": "서울특별시"}, square(127.0, 37.5, 0.20)),
            feature({"ctprvn_cd": "41", "ctp_kor_nm": "경기도"}, square(127.0, 37.2, 0.20))]
    return dotmap.Boundaries(sigg, emd, sido)


def km(geom):
    return shapely.transform(shape(geom), dotmap._to_km).buffer(1e-6)


def test_place_keeps_order_and_counts_and_stays_inside(bounds):
    X, Y, table = dotmap.place([("서울-가구", 400), ("서울-나구", 250), ("경기-화성시", 300)], bounds, jitter=0)
    assert len(X) == len(Y) == 950
    assert [(r["d"], r["s"], r["n"]) for r in table] == [("서울-가구", 0, 400), ("서울-나구", 400, 250), ("경기-화성시", 650, 300)]
    gagu, nagu = km(bounds.sigg[0]["geometry"]), km(bounds.sigg[1]["geometry"])
    hwaseong = km(bounds.sigg[2]["geometry"]).union(km(bounds.sigg[3]["geometry"]))
    assert shapely.contains_xy(gagu, X[:400], Y[:400]).all()
    assert shapely.contains_xy(nagu, X[400:650], Y[400:650]).all()
    assert shapely.contains_xy(hwaseong, X[650:], Y[650:]).all()


def test_place_is_deterministic(bounds):
    a = dotmap.place([("서울-가구", 120), ("서울-나구", 80)], bounds)
    b = dotmap.place([("서울-가구", 120), ("서울-나구", 80)], bounds)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_towns_get_more_dots_than_countryside(bounds):
    # 무읍 and 정면 have the same area; 읍 weighs 1.2, 면 0.3
    X, Y, _ = dotmap.place([("경기-화성시", 1000)], bounds, jitter=0)
    eup = shapely.contains_xy(km(bounds.emd[4]["geometry"]), X, Y).sum()
    myeon = shapely.contains_xy(km(bounds.emd[3]["geometry"]), X, Y).sum()
    assert eup + myeon == 1000 and eup > 3 * myeon


def test_unknown_district_is_an_error(bounds):
    with pytest.raises(ValueError):
        dotmap.district_features("부산-해운대구", bounds.sigg)


def test_outlines_and_extent(bounds):
    ol = dotmap.outlines(bounds)
    assert len(ol["sido"]) == 2 and all(p.startswith("M") and p.endswith("Z") for p in ol["sido"])
    assert [o["n"] for o in ol["seoul"]] == ["가구", "나구"]
    w, h = dotmap.extent(bounds)
    assert w > 0 and h > 0
