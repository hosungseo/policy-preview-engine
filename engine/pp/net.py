"""Small HTTP helpers on httpx, shared by the model clients, the notice adapter and the data scripts.

Only http(s) URLs are accepted. Errors come back as two kinds the callers already distinguish: HTTPError for an
answer with an error status (with code, headers and the first bytes of the body) and NetError for no answer at all.
"""
from __future__ import annotations

import httpx

UA = {"User-Agent": "Mozilla/5.0"}


class NetError(Exception):
    """No usable answer: connection refused, DNS failure, timeout."""


class HTTPError(Exception):
    def __init__(self, code: int, headers: dict, body: bytes):
        super().__init__(f"HTTP {code}")
        self.code, self.headers, self.body = code, headers, body


def _send(method: str, url: str, **kw) -> bytes:
    if not url.startswith(("https://", "http://")):
        raise NetError(f"unsupported URL: {url[:60]}")
    try:
        resp = httpx.request(method, url, follow_redirects=True, **kw)
    except httpx.HTTPError as e:
        raise NetError(f"{type(e).__name__}: {e}") from e
    if resp.status_code >= 400:
        raise HTTPError(resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, resp.content[:200])
    return resp.content


def get(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 60) -> bytes:
    return _send("GET", url, params=params, headers=headers or UA, timeout=timeout)


def post(url: str, body: bytes, *, headers: dict, timeout: float = 60) -> bytes:
    return _send("POST", url, content=body, headers=headers, timeout=timeout)
