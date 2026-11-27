"""Operator-issued access codes, sessions and login throttling."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from .db import Database, now

CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i
CODE_LEN = 12  # ~59 bits
ATTEMPT_WINDOW = timedelta(minutes=10)
ATTEMPT_LIMIT = 10


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def hash_code(code: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(code.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_code(code: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(code.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(digest.hex(), digest_hex)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def add_user(db: Database, email: str) -> str:
    code = new_code()
    with db.tx() as con:
        con.execute("INSERT INTO users(email, code_hash, created_at) VALUES (?, ?, ?)",
                    (normalize_email(email), hash_code(code), now()))
    return code


DEMO_EMAIL = "reviewer@example.org"


def demo_user(db: Database) -> dict:
    """The shared account used when demo login is on. Created on first use with a code nobody is told,
    so it cannot be entered through the login form until an operator resets its code."""
    row = db.one("SELECT id, email FROM users WHERE email=?", (DEMO_EMAIL,))
    if not row:
        add_user(db, DEMO_EMAIL)
        row = db.one("SELECT id, email FROM users WHERE email=?", (DEMO_EMAIL,))
    return {"id": row["id"], "email": row["email"]}


def reset_code(db: Database, email: str) -> str:
    code = new_code()
    with db.tx() as con:
        cur = con.execute("UPDATE users SET code_hash=? WHERE email=?", (hash_code(code), normalize_email(email)))
        if cur.rowcount == 0:
            raise KeyError(email)
        con.execute("DELETE FROM sessions WHERE user_id=(SELECT id FROM users WHERE email=?)", (normalize_email(email),))
    return code


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def throttled(db: Database, keys: list[str]) -> bool:
    since = (datetime.now(timezone.utc) - ATTEMPT_WINDOW).isoformat(timespec="seconds")
    for key in keys:
        row = db.one("SELECT COUNT(*) AS n FROM login_attempts WHERE key=? AND at>=?", (key, since))
        if row["n"] >= ATTEMPT_LIMIT:
            return True
    return False


def login(db: Database, email: str, code: str, ip: str, session_days: int) -> tuple[str, int] | None:
    """Returns (token, user_id) or None. Raises PermissionError when throttled."""
    email = normalize_email(email)
    keys = [f"email:{email}", f"ip:{ip}"]
    if throttled(db, keys):
        raise PermissionError("throttled")
    user = db.one("SELECT id, code_hash, disabled FROM users WHERE email=?", (email,))
    ok = bool(user) and not user["disabled"] and verify_code(code.strip(), user["code_hash"])
    if not ok:
        with db.tx() as con:
            for key in keys:
                con.execute("INSERT INTO login_attempts(key, at) VALUES (?, ?)", (key, now()))
        return None
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=session_days)).isoformat(timespec="seconds")
    with db.tx() as con:
        con.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                    (_token_hash(token), user["id"], now(), expires))
        con.execute("DELETE FROM login_attempts WHERE key=?", (keys[0],))
    return token, user["id"]


def session_user(db: Database, token: str | None) -> dict | None:
    if not token:
        return None
    row = db.one("SELECT u.id, u.email, s.expires_at FROM sessions s JOIN users u ON u.id=s.user_id "
                 "WHERE s.token_hash=? AND u.disabled=0", (_token_hash(token),))
    if not row or row["expires_at"] < now():
        return None
    return {"id": row["id"], "email": row["email"]}


def logout(db: Database, token: str | None) -> None:
    if token:
        with db.tx() as con:
            con.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))
