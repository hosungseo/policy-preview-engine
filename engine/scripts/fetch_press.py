"""Copy press-release excerpts verbatim for a policy series (the script copies; nobody retypes).

  ../.venv/bin/python scripts/fetch_press.py show <url>
  ../.venv/bin/python scripts/fetch_press.py cut <url> --pair "<start>" "<end>" [--pair "<start>" "<end>"]
  ../.venv/bin/python scripts/fetch_press.py verify series/housing.json

A URL may be an HTML page, an HWPX attachment or a PDF (korea.kr "download.do?fileId=…").
`cut` prints each excerpt from its start anchor through its end anchor exactly as on the page, joined by a
line holding only "…". `verify` re-fetches every measure's page and checks the stored text still matches.
"""
import argparse
import html
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

import httpx
from defusedxml import ElementTree as ET

HP = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"


def html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", raw)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</?(p|div|li|tr|td|th|h\d|dd|dt|ul|ol|table)\b[^>]*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines()]
    return "\n".join(line for line in lines if line)


def _clean(lines) -> str:
    out = [re.sub(r"[ \t]+", " ", line.replace("\xa0", " ")).strip() for line in lines]
    return "\n".join(line for line in out if line)


def hwpx_to_text(data: bytes) -> str:
    """One line per HWPX paragraph in document order; paragraphs inside table cells follow their table's paragraph."""
    z = zipfile.ZipFile(io.BytesIO(data))
    sections = sorted(n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n))
    lines = []
    for name in sections:
        for p in ET.fromstring(z.read(name)).iter(HP + "p"):
            lines.append("".join("".join(t.itertext()) for run in p.findall(HP + "run") for t in run.findall(HP + "t")))
    return _clean(lines)


def pdf_to_text(data: bytes) -> str:
    """Reading-order text of a PDF (poppler's pdftotext), one line per text line."""
    out = subprocess.run(["pdftotext", "-enc", "UTF-8", "-", "-"], input=data, capture_output=True, check=True).stdout
    return _clean(out.decode("utf-8", errors="replace").splitlines())


def to_text(raw: bytes) -> str:
    if raw[:2] == b"PK":
        return hwpx_to_text(raw)
    if raw[:4] == b"%PDF":
        return pdf_to_text(raw)
    for enc in ("utf-8", "euc-kr"):
        try:
            return html_to_text(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return html_to_text(raw.decode("utf-8", errors="replace"))


def cut(text: str, pairs: list[tuple[str, str]]) -> str:
    parts = []
    for start, end in pairs:
        i = text.find(start)
        if i < 0:
            raise ValueError(f"start anchor not found: {start[:40]!r}")
        k = i + len(start)
        j = k - len(end) if start.endswith(end) else text.find(end, k)
        if j < 0:
            raise ValueError(f"end anchor not found after the start: {end[:40]!r}")
        parts.append(text[i:j + len(end)].strip())
    return "\n…\n".join(parts)


def fetch(url: str) -> bytes:
    resp = httpx.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    show = sub.add_parser("show")
    show.add_argument("url")
    c = sub.add_parser("cut")
    c.add_argument("url")
    c.add_argument("--pair", nargs=2, action="append", required=True)
    v = sub.add_parser("verify")
    v.add_argument("series")
    args = ap.parse_args()
    if args.cmd == "verify":
        data = json.loads(Path(args.series).read_text(encoding="utf-8"))
        bad = 0
        for m in data["measures"]:
            if m["source"].get("text_kind") == "summary":  # our own summary in place of an unlicensed original
                print("skip", m["id"], "summary, original at", m["source"]["url"])
                continue
            got = cut(to_text(fetch(m["source"].get("file") or m["source"]["url"])), [tuple(p) for p in m["source"]["excerpts"]])
            ok = got == m["text"]
            bad += not ok
            print("ok  " if ok else "DIFF", m["id"], len(m["text"]))
        raise SystemExit(1 if bad else 0)
    text = to_text(fetch(args.url))
    print(text if args.cmd == "show" else cut(text, [tuple(p) for p in args.pair]))


if __name__ == "__main__":
    main()
