"""Download MOLIT real-transaction records (매매·전월세) for every persona district and month.

  ../.venv/bin/python scripts/fetch_rtms.py [--from 202503 --to 202607] [--only AptTrade,AptRent] [--codes 11680] [--delay 2.0]

One file per (service, 법정동 code, month) under data/official/rtms/<service>/<code>_<yyyymm>.json holding every item's
fields as strings, so the aggregation can change without downloading again. Existing files are skipped, so the
script resumes. Each service runs in its own thread at one request per --delay seconds (the gateway answers 429 to
bursts); a 429 waits a minute and retries. Codes come from series/official/regions.json.
"""
import argparse
import json
import os
import threading
import time
import urllib.parse
from pathlib import Path

import httpx
from defusedxml import ElementTree as ET

ENGINE = Path(__file__).resolve().parents[1]
OUT = ENGINE.parent / "data" / "official" / "rtms"
SERVICES = {
    "AptTrade": "RTMSDataSvcAptTrade", "AptRent": "RTMSDataSvcAptRent",
    "RHTrade": "RTMSDataSvcRHTrade", "RHRent": "RTMSDataSvcRHRent",
    "SHTrade": "RTMSDataSvcSHTrade", "SHRent": "RTMSDataSvcSHRent",
    "OffiTrade": "RTMSDataSvcOffiTrade", "OffiRent": "RTMSDataSvcOffiRent",
}
ROWS = 1000


def _key() -> str:
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not key:
        raise SystemExit("DATA_GO_KR_KEY is not set (공공데이터포털 서비스 키)")
    return key


def months(start: str, end: str) -> list[str]:
    y, m = int(start[:4]), int(start[4:])
    out = []
    while f"{y}{m:02d}" <= end:
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def fetch_page(svc: str, code: str, ym: str, page: int, key: str) -> tuple[int, list[dict]]:
    q = urllib.parse.urlencode({"serviceKey": key, "LAWD_CD": code, "DEAL_YMD": ym, "pageNo": str(page), "numOfRows": str(ROWS)})
    url = f"https://apis.data.go.kr/1613000/{svc}/get{svc}?{q}"
    for attempt in range(8):
        try:
            r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
            if r.status_code == 429:
                time.sleep(60)
                continue
            r.raise_for_status()
            body = r.content
            root = ET.fromstring(body)
            code_el = root.find(".//resultCode")
            if code_el is not None and code_el.text not in ("000", "00"):
                raise RuntimeError(f"resultCode {code_el.text}: {root.findtext('.//resultMsg')}")
            total = int(root.findtext(".//totalCount") or 0)
            items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
            return total, items
        except (httpx.HTTPError, ET.ParseError, RuntimeError):
            if attempt >= 3:
                raise
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("gave up after repeated 429")


def run_service(name: str, codes: list[str], yms: list[str], delay: float, key: str, log) -> None:
    svc = SERVICES[name]
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    done = calls = records = 0
    for code in codes:
        for ym in yms:
            path = folder / f"{code}_{ym}.json"
            if path.exists():
                done += 1
                continue
            try:
                total, items = fetch_page(svc, code, ym, 1, key)
                calls += 1
                time.sleep(delay)
                page = 1
                while len(items) < total:
                    page += 1
                    _, more = fetch_page(svc, code, ym, page, key)
                    calls += 1
                    time.sleep(delay)
                    if not more:
                        break
                    items += more
            except Exception as e:  # keep going; the missing file is retried on the next run
                log(f"[{name}] {code} {ym} FAILED: {str(e)[:200]}")
                continue
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
            tmp.rename(path)
            done += 1
            records += len(items)
            if done % 100 == 0:
                log(f"[{name}] {done}/{len(codes) * len(yms)} files, {calls} calls, {records} records")
    log(f"[{name}] finished: {done}/{len(codes) * len(yms)} files, {calls} calls this run, {records} records")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="202503")
    ap.add_argument("--to", dest="end", default="202607")
    ap.add_argument("--only", default="")
    ap.add_argument("--delay", type=float, default=2.0)
    ap.add_argument("--codes", default="", help="comma-separated 법정동 codes (default: every persona district)")
    args = ap.parse_args()
    regions = json.loads((ENGINE / "series" / "official" / "regions.json").read_text(encoding="utf-8"))["districts"]
    codes = sorted({p["code"] for v in regions.values() for p in v["lawd"]})
    if args.codes:
        codes = [c for c in args.codes.split(",") if c]
    yms = months(args.start, args.end)
    names = [n for n in SERVICES if not args.only or n in args.only.split(",")]
    lock = threading.Lock()

    def log(msg: str) -> None:
        with lock:
            print(time.strftime("%H:%M:%S"), msg, flush=True)

    log(f"{len(codes)} codes x {len(yms)} months x {len(names)} services")
    key = _key()
    threads = [threading.Thread(target=run_service, args=(n, codes, yms, args.delay, key, log)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
