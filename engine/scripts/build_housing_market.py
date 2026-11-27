"""Summarise the downloaded MOLIT real transactions per persona district and measure window.

  ../.venv/bin/python scripts/build_housing_market.py [--series series/housing.json]

Window = the three calendar months before the measure's announcement month (6·27 → 2025-03..05).
Per district, window and housing type (아파트 Apt, 연립다세대 RH, 단독다가구 SH, 오피스텔 Offi):
  trade: n, median price, median price per ㎡ (만원), share of deals above 6억·15억·25억 (cancelled deals dropped)
  rent:  n, share of monthly-rent contracts, median jeonse deposit, median monthly rent and its deposit (만원)
Districts with fewer than MIN_N records in a cell get the cell with "small": true so later steps can fall back.
Also a price level per district for grouping results: apartment sale stats over every month the windows span
(2025-03..2026-07 for the housing series), so a person's group does not change from measure to measure.
Writes series/official/housing_market.json.
"""
import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
RAW = ENGINE.parent / "data" / "official" / "rtms"
TYPES = {"Apt": "아파트", "RH": "연립다세대", "SH": "단독다가구", "Offi": "오피스텔"}
THRESHOLDS = {"over_6": 60000, "over_15": 150000, "over_25": 250000}  # 만원
MIN_N = 10


def _num(s: str) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def window(date: str) -> list[str]:
    y, m = int(date[:4]), int(date[5:7])
    out = []
    for _ in range(3):
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        out.append(f"{y}{m:02d}")
    return sorted(out)


def span(windows: dict[str, list[str]]) -> list[str]:
    """Every month from the earliest window month to the latest."""
    first, last = min(min(w) for w in windows.values()), max(max(w) for w in windows.values())
    y, m, out = int(first[:4]), int(first[4:]), []
    while f"{y}{m:02d}" <= last:
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _records(kind: str, parts: list[dict], yms: list[str]) -> list[dict] | None:
    rows = []
    for p in parts:
        for ym in yms:
            f = RAW / kind / f"{p['code']}_{ym}.json"
            if not f.exists():
                return None  # not downloaded yet
            for r in json.loads(f.read_text(encoding="utf-8")):
                umd = r.get("umdNm", "").split(" ")[0]
                if "umd_in" in p and umd not in p["umd_in"]:
                    continue
                if "umd_not_in" in p and umd in p["umd_not_in"]:
                    continue
                rows.append(r)
    return rows


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 1) if xs else None


def trade_stats(rows: list[dict]) -> dict:
    prices, per_m2 = [], []
    for r in rows:
        if r.get("cdealType") == "O":
            continue  # 계약 해제
        price = _num(r.get("dealAmount", ""))
        if price is None:
            continue
        prices.append(price)
        area = _num(r.get("excluUseAr") or r.get("totalFloorAr") or "")
        if area:
            per_m2.append(price / area)
    out = {"n": len(prices), "median": _median(prices), "median_per_m2": _median(per_m2)}
    for k, v in THRESHOLDS.items():
        out[k] = round(sum(p > v for p in prices) / len(prices), 4) if prices else None
    out["small"] = len(prices) < MIN_N
    return out


def rent_stats(rows: list[dict]) -> dict:
    jeonse, monthly, monthly_dep = [], [], []
    for r in rows:
        dep, rent = _num(r.get("deposit", "")), _num(r.get("monthlyRent", ""))
        if dep is None or rent is None:
            continue
        if rent == 0:
            jeonse.append(dep)
        else:
            monthly.append(rent)
            monthly_dep.append(dep)
    n = len(jeonse) + len(monthly)
    return {"n": n, "monthly_share": round(len(monthly) / n, 4) if n else None,
            "jeonse_median": _median(jeonse), "monthly_rent_median": _median(monthly),
            "monthly_deposit_median": _median(monthly_dep), "small": n < MIN_N}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default=str(ENGINE / "series" / "housing.json"))
    args = ap.parse_args()
    series = json.loads(Path(args.series).read_text(encoding="utf-8"))
    regions = json.loads((ENGINE / "series" / "official" / "regions.json").read_text(encoding="utf-8"))["districts"]
    windows = {m["id"]: window(m["date"]) for m in series["measures"]}
    out: dict = defaultdict(dict)
    missing = 0
    for d, v in regions.items():
        for mid, yms in windows.items():
            cell = {}
            for t in TYPES:
                trade, rent = _records(f"{t}Trade", v["lawd"], yms), _records(f"{t}Rent", v["lawd"], yms)
                if trade is None or rent is None:
                    missing += 1
                    continue
                cell[t] = {"trade": trade_stats(trade), "rent": rent_stats(rent)}
            if cell:
                out[d][mid] = cell
    months = span(windows)
    levels = {}
    for d, v in regions.items():
        trade = _records("AptTrade", v["lawd"], months)
        if trade is None:
            missing += 1
            continue
        levels[d] = trade_stats(trade)
    (ENGINE / "series" / "official" / "housing_market.json").write_text(json.dumps({
        "source": "국토교통부 실거래가 공개자료(공공데이터포털 오픈API): 아파트·연립다세대·단독다가구·오피스텔 매매·전월세",
        "unit": "만원", "window": "대책 발표 달 직전 3개 달", "types": TYPES, "min_n": MIN_N,
        "windows": windows, "districts": out,
        "level": {"months": months, "note": "기간 전체 아파트 매매(해제 거래 뺌)"}, "levels": levels},
        ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(out)} districts, {missing} district-window-type cells not downloaded yet")


if __name__ == "__main__":
    main()
