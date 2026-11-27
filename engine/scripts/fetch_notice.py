"""Copy a lawmaking.go.kr legislative notice verbatim into a policy JSON (reason + main contents only).

Run:
  ../.venv/bin/python scripts/fetch_notice.py --notice 88826 --policy-id life-safety-decree \
      --title "생명안전기본법 시행령 제정안" --period "2026. 9. 23. ~ 2026. 11. 2." \
      --out policies/life-safety-decree.json
"""
import argparse
import html
import json
import re
from pathlib import Path

import httpx

URL = "https://opinion.lawmaking.go.kr/gcom/ogLmPp/{notice}"


def html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</?(p|div|li|tr|td|th|h\d|dd|dt|ul|ol|table)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines()]
    return "\n".join(line for line in lines if line)


def extract(text: str) -> str:
    start = re.search(r"(?m)^1\.\s*(제정|개정)\s*이유", text)
    if not start:
        raise SystemExit("could not find '1. 제정이유/개정이유'")
    body = text[start.start():]
    end = re.search(r"(?m)^3\.\s*(?:의견|$)", body)
    if end:
        body = body[:end.start()]
    return body.strip()


def fetch(notice: str) -> str:
    resp = httpx.get(URL.format(notice=notice), headers={"User-Agent": "Mozilla/5.0"}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.content.decode("utf-8", errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--notice", required=True)
    ap.add_argument("--policy-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--period", required=True)
    ap.add_argument("--agency", default="행정안전부")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    text = extract(html_to_text(fetch(args.notice)))
    policy = {
        "id": args.policy_id, "title": args.title, "kind": "입법예고", "agency": args.agency,
        "source": {"url": URL.format(notice=args.notice), "period": args.period,
                   "note": "국민참여입법센터 입법예고문의 제정이유·주요내용을 원문 그대로 옮김"},
        "text": text,
    }
    args.out.write_text(json.dumps(policy, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out} ({len(text)} chars)")


if __name__ == "__main__":
    main()
