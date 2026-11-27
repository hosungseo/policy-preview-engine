"""SQLite schema and per-thread connections."""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, code_hash TEXT NOT NULL,
  created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts (key TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS login_attempts_key ON login_attempts(key, at);
CREATE TABLE IF NOT EXISTS surveys (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL, policy_text TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, survey_id TEXT NOT NULL REFERENCES surveys(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL, status TEXT NOT NULL, spec TEXT NOT NULL, spec_hash TEXT NOT NULL,
  lint TEXT NOT NULL, retry_of TEXT, attempt INTEGER NOT NULL DEFAULT 0,
  done INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL, failed INTEGER NOT NULL DEFAULT 0,
  error_code TEXT, error_detail TEXT, result TEXT, panel_version TEXT, jev_model TEXT,
  estimate_usd REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active ON runs(survey_id) WHERE status IN ('queued','running');
CREATE INDEX IF NOT EXISTS runs_user_day ON runs(user_id, created_at);
CREATE TABLE IF NOT EXISTS answers (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, arm TEXT NOT NULL, uuid TEXT NOT NULL,
  probs TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (run_id, arm, uuid));
CREATE TABLE IF NOT EXISTS spend (
  id INTEGER PRIMARY KEY, run_id TEXT REFERENCES runs(id) ON DELETE SET NULL, user_id INTEGER,
  day TEXT NOT NULL, reserved_usd REAL NOT NULL, actual_usd REAL, input_tokens INTEGER, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS spend_day ON spend(day);
CREATE TABLE IF NOT EXISTS deeps (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE, user_id INTEGER NOT NULL, status TEXT NOT NULL,
  stage TEXT, attempt INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_detail TEXT, result TEXT, bundle TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class Database:
    """One connection per thread; every connection enforces foreign keys and waits on locks."""

    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()
        self.con.executescript(SCHEMA)  # executescript manages its own transaction
        with self.tx() as con:
            con.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=10.0, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA secure_delete=ON")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    @property
    def con(self) -> sqlite3.Connection:
        con = getattr(self._local, "con", None)
        if con is None:
            con = self._connect()
            self._local.con = con
        return con

    @contextmanager
    def tx(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        con = self.con
        con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield con
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("COMMIT")

    def one(self, sql: str, args: tuple = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, args).fetchone()

    def all(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, args).fetchall()

    def checkpoint(self) -> None:
        self.con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
