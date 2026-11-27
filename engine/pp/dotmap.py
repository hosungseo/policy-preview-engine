"""Personas as dots on a map of Korea.

Only a dot's district (시군구) is real: the persona DB says where each person lives. Inside the district a dot goes to
a random 읍면동, weighted by its type (동 1.0, 읍 1.2, 면 0.3) times its area, then to a uniform random spot inside it,
then a small blur so neighbourhood edges do not show as seams when zoomed in. The spot is an illustration.

Coordinates are km on a plain equirectangular projection: x grows east from 124.5°E, y grows south from 38.75°N.
Boundaries are GeoJSON files with 시군구 (sig_cd, full_nm), 읍면동 (emd_cd, full_nm, emd_kor_nm) and 시도 features.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import shape

LON0, LAT1, LATREF = 124.5, 38.75, 36.3
KX, KY = 111.32 * math.cos(math.radians(LATREF)), 110.57
CAP = 200_000          # candidate points per try: a sliver can never ask for billions
JITTER_KM = 0.12
SEED = 20260927
WEIGHT = {"동": 1.0, "가": 1.0, "로": 1.0, "읍": 1.2, "면": 0.3, "리": 0.3}
# persona DB province prefix -> boundary 시도 name
PROVINCE = {"강원": "강원특별자치도", "경기": "경기도", "경상남": "경상남도", "경상북": "경상북도", "광주": "광주광역시",
            "대구": "대구광역시", "대전": "대전광역시", "부산": "부산광역시", "서울": "서울특별시", "세종": "세종특별자치시",
            "울산": "울산광역시", "인천": "인천광역시", "전라남": "전라남도", "전북": "전북특별자치도", "제주": "제주특별자치도",
            "충청남": "충청남도", "충청북": "충청북도"}


def project(lon, lat):
    return (np.asarray(lon) - LON0) * KX, (LAT1 - np.asarray(lat)) * KY


def _to_km(coords: np.ndarray) -> np.ndarray:
    return np.stack(project(coords[:, 0], coords[:, 1]), 1)


def _polys(g):
    return list(g.geoms) if g.geom_type == "MultiPolygon" else [g]


@dataclass
class Boundaries:
    sigg: list[dict]
    emd: list[dict]
    sido: list[dict]

    @classmethod
    def load(cls, geo_dir: Path) -> "Boundaries":
        read = lambda name: json.loads((Path(geo_dir) / name).read_text(encoding="utf-8"))["features"]
        return cls(read("sigg-boundaries.geojson"), read("emd-boundaries.geojson"), read("sido-boundaries.geojson"))


def district_features(district: str, sigg: list[dict]) -> list[dict]:
    """The 시군구 features of a DB district ("서울-노원구"; "경기-화성시" covers its 구 split since 2026)."""
    prov, rest = district.split("-", 1)
    full = PROVINCE[prov] + ("" if prov == "세종" else " " + rest)
    hits = [f for f in sigg if f["properties"]["full_nm"] == full]
    if not hits:
        hits = [f for f in sigg if f["properties"]["full_nm"].startswith(full + " ")]
    if not hits:
        raise ValueError(f"no boundary for {district} ({full})")
    return hits


def _emd_of_sigg(b: Boundaries) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for i, f in enumerate(b.emd):
        out.setdefault(f["properties"]["emd_cd"][:5], []).append(i)
    for f in b.sigg:
        code, name = f["properties"]["sig_cd"], f["properties"]["full_nm"]
        if code not in out:   # codes changed with a reorganisation: fall back to the name prefix
            out[code] = [i for i, e in enumerate(b.emd) if e["properties"]["full_nm"].startswith(name + " ")]
        if not out[code]:
            raise ValueError(f"no 읍면동 for {name}")
    return out


def sample_in(parts: list, areas: np.ndarray, geom, k: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """k uniform random points inside a (multi)polygon given as prepared parts with their areas."""
    if not parts:   # no area at all: a small cloud at a point inside it
        c = geom.representative_point()
        return c.x + rng.normal(0, 0.03, k), c.y + rng.normal(0, 0.03, k)
    xs, ys = [], []
    for p, kk in zip(parts, rng.multinomial(k, areas / areas.sum())):
        if not kk:
            continue
        x0, y0, x1, y1 = p.bounds
        ratio = max((x1 - x0) * (y1 - y0), 1e-9) / p.area
        need = int(kk)
        for _ in range(40):
            m = min(int(need * 1.3 * ratio) + 32, CAP)
            cx, cy = rng.uniform(x0, x1, m), rng.uniform(y0, y1, m)
            ok = shapely.contains_xy(p, cx, cy)
            cx, cy = cx[ok][:need], cy[ok][:need]
            xs.append(cx); ys.append(cy); need -= len(cx)
            if need <= 0:
                break
        if need > 0:   # a sliver: the rest go to a point inside it
            c = p.representative_point()
            xs.append(c.x + rng.normal(0, 0.02, need)); ys.append(c.y + rng.normal(0, 0.02, need))
    return np.concatenate(xs), np.concatenate(ys)


def place(districts: list[tuple[str, int]], b: Boundaries, seed: int = SEED,
          jitter: float = JITTER_KM) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Dots for [(district, count), ...] in that order: x, y (km) and a table of {d, s, n, cx, cy} per district."""
    geo = [shapely.transform(shape(f["geometry"]), _to_km) for f in b.emd]
    parts = []
    for g in geo:
        ps = [p for p in _polys(g) if p.area > 0]
        for p in ps:
            shapely.prepare(p)
        parts.append((ps, np.array([p.area for p in ps]), g))
    members_of = _emd_of_sigg(b)
    rng = np.random.default_rng(seed)
    total = sum(n for _, n in districts)
    X, Y = np.zeros(total), np.zeros(total)
    table, pos = [], 0
    for d, n in districts:
        members = [i for f in district_features(d, b.sigg) for i in members_of[f["properties"]["sig_cd"]]]
        w = np.array([WEIGHT.get(b.emd[i]["properties"]["emd_kor_nm"][-1], 1.0) * max(geo[i].area, 1e-4)
                      for i in members])
        xs, ys = [], []
        for i, k in zip(members, rng.multinomial(n, w / w.sum())):
            if k:
                cx, cy = sample_in(*parts[i], int(k), rng)
                xs.append(cx); ys.append(cy)
        xs, ys = np.concatenate(xs), np.concatenate(ys)
        if jitter:
            xs, ys = xs + rng.normal(0, jitter, n), ys + rng.normal(0, jitter, n)
        perm = rng.permutation(n)   # which person gets which spot
        X[pos:pos + n], Y[pos:pos + n] = xs[perm], ys[perm]
        table.append({"d": d, "s": pos, "n": n, "cx": round(float(xs.mean()), 2), "cy": round(float(ys.mean()), 2)})
        pos += n
    return X, Y, table


def extent(b: Boundaries) -> tuple[float, float]:
    """Width and height (km) of the country's bounding box in map coordinates."""
    xs, ys = [], []
    for f in b.sido:
        for p in _polys(shape(f["geometry"])):
            c = _to_km(np.array(p.exterior.coords))
            xs += [c[:, 0].min(), c[:, 0].max()]; ys += [c[:, 1].min(), c[:, 1].max()]
    return round(float(max(xs)), 2), round(float(max(ys)), 2)


def _path(g, tol: float, digits: int) -> str:
    d = ""
    for p in _polys(g.simplify(tol)):
        c = _to_km(np.array(p.exterior.coords))
        if len(c) < 4:
            continue
        d += "M" + "L".join(f"{x:.{digits}f},{y:.{digits}f}" for x, y in c) + "Z"
    return d


def outlines(b: Boundaries) -> dict:
    """SVG paths (km): the 17 시도, and Seoul's 25 구 with their names."""
    return {
        "sido": [p for p in (_path(shape(f["geometry"]), 0.004, 1) for f in b.sido) if p],
        "seoul": [{"n": f["properties"]["sig_kor_nm"], "d": _path(shape(f["geometry"]), 0.0012, 2)}
                  for f in b.sigg if f["properties"]["full_nm"].startswith("서울특별시 ")],
    }
