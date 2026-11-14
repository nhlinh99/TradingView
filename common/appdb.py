"""SQLite nhỏ cho cài đặt của người dùng: watchlist, layout, hình vẽ, alert."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import store

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
  symbol   TEXT PRIMARY KEY,
  position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS layouts (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  name    TEXT NOT NULL UNIQUE,
  payload TEXT NOT NULL            -- JSON
);
CREATE TABLE IF NOT EXISTS drawings (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  layout_id INTEGER REFERENCES layouts(id) ON DELETE CASCADE,
  symbol    TEXT NOT NULL,
  kind      TEXT NOT NULL,
  payload   TEXT NOT NULL          -- JSON
);
CREATE TABLE IF NOT EXISTS alerts (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol    TEXT NOT NULL,
  condition TEXT NOT NULL,         -- JSON
  enabled   INTEGER NOT NULL DEFAULT 1,
  created   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
-- Nhật ký backfill: ngày nào của dataset nào đã tải và kiểm checksum xong.
CREATE TABLE IF NOT EXISTS backfill_log (
  dataset   TEXT NOT NULL,
  symbol    TEXT NOT NULL,
  day       TEXT NOT NULL,         -- YYYY-MM-DD (UTC)
  rows      INTEGER NOT NULL,
  sha256    TEXT NOT NULL,
  loaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (dataset, symbol, day)
);
"""


def db_path() -> Path:
    return store.data_dir() / "app.sqlite"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path())
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init() -> Path:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect()
    try:
        con.executescript(SCHEMA)
        con.commit()
    finally:
        con.close()
    return path
